# Feature 5 — Data Extraction (`src/extraction.py`, `src/prompts.py`)

> Pipeline position: `extract` — fifth node. The vision-model call that turns each page image into fields + confidence scores.

## Purpose

Data extraction is the step that actually reads the document: it sends each enhanced page image to a vision model and turns the reply into structured JSON — a flat map of field names to values plus a per-field confidence score. The prompt wording lives in `src/prompts.py`; `src/extraction.py` only handles the mechanics (image encoding, the model request, response parsing). An optional JSON template (`data/Template/test.json`, loaded via `TEMPLATE_FIELDS` in `src/config.py`) locks the extraction to a fixed set of field names; without a template the prompt falls back to free-form mode.

## How It Works

1. **Prompt selection (at import time).** `src/prompts.py:88` builds the prompt once: `EXTRACTION_PROMPT = build_extraction_prompt(config.TEMPLATE_FIELDS)`. If `TEMPLATE_FIELDS` is non-empty the prompt demands *exactly* those fields; if it is empty (template missing or broken) the prompt switches to free-form mode (see [Prompting & Template](#prompting--template)).
2. **Engine creation.** `extract_node` (`src/pipeline_graph.py:123`) creates one `ExtractionEngine()` shared across all pages. With no arguments the client is `None` (created lazily), `max_image_side` is `MAX_IMAGE_SIDE = 2048` (`src/extraction.py:34`), and `template_fields` defaults to `config.TEMPLATE_FIELDS` (`src/extraction.py:62`).
3. **Per-page call.** For every enhanced page image, `extract_node` rebuilds a `RoutingDecision(model, tier, score)` from the routing state and calls `engine.extract(image, decision)` (`src/extraction.py:66`).
4. **Image encoding.** `_to_base64_png` (`src/extraction.py:111`) converts the PIL image to RGB, proportionally downscales it if the long side exceeds `max_image_side` (2048 px by default), saves it as PNG into a `BytesIO` buffer, and returns the base64 (ASCII) string.
5. **Client & model.** `_get_client` (`src/extraction.py:104`) lazily calls `ModelRouter.create_async_client()`, which builds an async **OpenAI-compatible** client — `from openai import AsyncOpenAI; AsyncOpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)` (`src/router.py:77`). The model is not chosen here: the routing node upstream mapped the page's quality tier to a model (`clear` → small, `blurry` → medium, `very_blurry` → large via `config.TIER_MODEL_MAP`), and extraction simply uses `decision.model`.
6. **Request.** One chat-completions call per page (`src/extraction.py:75`): `client.chat.completions.create(model=decision.model, messages=[{"role": "user", "content": [{"type": "text", "text": EXTRACTION_PROMPT}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,<payload>"}}]}], max_tokens=1000)`. The prompt text and the page image go in a single user message.
7. **Response parsing.** The reply text is `response.choices[0].message.content or ""` and goes through the static `_parse_json_object` (`src/extraction.py:124`): leading ` ``` ` code fences and a `json` tag are stripped, then the substring from the first `{` to the last `}` is `json.loads`-ed (models often wrap JSON in prose). If no object exists or parsing fails, it returns `({}, {})` with a warning instead of raising. If the parsed value is not a dict it is wrapped as `{"result": data}` with an empty confidence map.
8. **Field split.** For each key of the parsed object (`src/extraction.py:150`): if the value is a dict containing `"value"`, `fields[name]` gets that value and `confidence_scores[name]` gets `int(confidence)` when it is a number in 0–100, otherwise `0`. Any other shape is stored raw with confidence `0`.
9. **Result.** The `ExtractionResult` (`src/extraction.py:37`) holds `fields`, `confidence_scores`, `model` (echoed from the decision), `processing_time` (seconds, rounded to 2 decimals), `success` (set `True` only when the call and parse both complete), and `error` (`"<ExceptionType>: <message>"` on failure). `extract_node` serializes one entry per page: `{"page", "model", "extracted_fields", "field_confidence_scores", "success", "error"}` (`src/pipeline_graph.py:138`).

```mermaid
flowchart TD
    T["data/Template/test.json<br/>(TEMPLATE_PATH)"] --> L["_load_template_fields<br/>src/config.py"]
    L -->|keys found| TB["build_extraction_prompt(template_fields)<br/>locked to exact fields"]
    L -->|missing or broken -> []| FB["build_extraction_prompt(None)<br/>free-form: at most 10 fields"]
    TB --> P["EXTRACTION_PROMPT<br/>(built once at import)"]
    FB --> P
    I["Enhanced page image"] --> E["_to_base64_png<br/>RGB, downscale to 2048px, base64"]
    P --> R["chat.completions.create<br/>model = decision.model, max_tokens=1000"]
    E --> R
    D["RoutingDecision<br/>from route node"] --> R
    R --> X["_parse_json_object"]
    X --> Y{"valid JSON object?"}
    Y -->|yes| Z["fields + confidence_scores"]
    Y -->|no / unparseable| N["empty fields"]
    Z --> O["ExtractionResult<br/>success = True"]
    N --> O
    R -.->|exception| F["ExtractionResult<br/>success = False, error set"]
```

## Inputs & Outputs

| Direction | Name | Type | Source / target |
|---|---|---|---|
| Input | `image` | `PIL.Image.Image` | enhanced page image from the `enhance` node |
| Input | `decision` | `RoutingDecision` (`model: str`, `tier: str`, `score: float`) | rebuilt per page from the `route` node's state |
| Input | `EXTRACTION_PROMPT` | `str` | `src/prompts.py`, built from `config.TEMPLATE_FIELDS` |
| Output | `ExtractionResult.fields` | `dict` | field name → extracted value |
| Output | `ExtractionResult.confidence_scores` | `dict[str, int]` | field name → confidence 0–100 (0 when unknown/invalid) |
| Output | `ExtractionResult.model` | `str` | model actually called (`decision.model`) |
| Output | `ExtractionResult.processing_time` | `float` | seconds, rounded to 2 decimals |
| Output | `ExtractionResult.success` / `.error` | `bool` / `str \| None` | `True` on clean call+parse; otherwise error string |
| Output | pipeline entry | `dict` | `{"page", "model", "extracted_fields", "field_confidence_scores", "success", "error"}` per page (`src/pipeline_graph.py:138`) |

## Configuration

All values come from `.env` through `src/config.py` — nothing is hard-coded.

| `.env` key | `src/config.py` attribute | Default | Role in extraction |
|---|---|---|---|
| `API_KEY` | `API_KEY` (`src/config.py:21`) | `""` | auth for the OpenAI-compatible gateway client |
| `BASE_URL` | `BASE_URL` (`src/config.py:22`) | `""` | gateway endpoint (`OpenAI(base_url=...)`) |
| `IMAGE_MODEL_LARGE` | `MODEL_IMAGE_LARGE` (`src/config.py:25`) | `mistralai/mistral-large-2512` | model for the `very_blurry` tier |
| `IMAGE_MODEL_MEDIUM` | `MODEL_IMAGE_MEDIUM` (`src/config.py:26`) | `mistralai/mistral-medium-3.5` | model for the `blurry` tier |
| `IMAGE_MODEL_SMALL` | `MODEL_IMAGE_SMALL` (`src/config.py:27`) | `mistralai/mistral-small-2603` | model for the `clear` tier |
| `TIER_CLEAR_MODEL` / `TIER_BLURRY_MODEL` / `TIER_VERY_BLURRY_MODEL` | `TIER_MODEL_MAP` (`src/config.py:30`) | falls back to the three `IMAGE_MODEL_*` values | tier → model table consumed by the router; decides `decision.model` |
| `TEMPLATE_PATH` | `TEMPLATE_PATH` (`src/config.py:48`) | `data/Template/test.json` | JSON template whose keys fix the extracted field names |
| — | `TEMPLATE_FIELDS` (`src/config.py:69`) | `[]` if template missing/broken | field-name list handed to `build_extraction_prompt` |

Fixed code-level settings: `MAX_IMAGE_SIDE = 2048` (`src/extraction.py:34`) and `max_tokens=1000` in the request (`src/extraction.py:91`).

## Prompting & Template

All prompt text lives in `src/prompts.py` so it can be tuned without touching pipeline logic.

**Output format** (both modes, `src/prompts.py:80`): the prompt demands exactly `{"field_name": {"value": "extracted_value", "confidence": 85}}` and ends with *"No markdown, no code fences, no explanations."*

**Grounding rules** (`_GROUNDING_RULES`, `src/prompts.py:22`): a "STRICT GROUNDING RULES (highest priority)" block instructs the model to extract only clearly visible text, copy values exactly ("do NOT guess, infer, auto-complete, translate, or correct spelling"), never return partial/truncated values, never reconstruct blurry pages from layout or document type, never invent dates/amounts/names/reference numbers, and to self-report confidence honestly — high (70–89) only for fully legible labelled text, low (0–30) when partial — with rule 7: *"NEVER give a confidence score of 90 to 100. 89 is the maximum possible score."*

**Template (locked) mode** — used when `TEMPLATE_FIELDS` is non-empty (`src/prompts.py:49`): the prompt lists the fields (`Extract EXACTLY these fields and no others: "document_no", "dete", ...`), demands one entry per field in the same order, and requires `"value": null` + `"confidence": 0` for missing or unreadable fields — "never omit the field and never guess its value."

**Free-form mode** — used when the template is absent or broken (`src/prompts.py:61`): the prompt asks for "ONLY the top most important fields" (at most `MAX_FIELDS = 10`, `src/prompts.py:20`) and adds two extra rules: skip unreadable fields entirely (no placeholders like `'N/A'`), and return exactly `{}` when nothing can be read with certainty.

**Template file** — `data/Template/test.json` is a plain JSON map under `"extracted_fields"`; its **key names** define the field set (the string values are ignored). The shipped template fixes 8 fields: `document_no`, `dete`, `buyer`, `buyer-trn`, `seller`, `seller-trn`, `dn`, `sub total`. `_load_template_fields` (`src/config.py:53`) reads the file, takes the `extracted_fields` block (or the whole object / a list), and returns the key names; any `OSError` or `JSONDecodeError` yields `[]`, which flips the prompt to free-form mode.

## Error Handling & Edge Cases

| Case | Behaviour |
|---|---|
| Any exception during encoding, request, or parsing | caught in `extract` (`src/extraction.py:98`); `result.error = "<Type>: <msg>"`, `success` stays `False`, logged via `logger.error`; the pipeline never stops on a bad page |
| Model reply contains no JSON object | `_parse_json_object` warns and returns `({}, {})` (`src/extraction.py:135`) — empty fields, no exception |
| Model reply is invalid JSON | warns and returns `({}, {})` (`src/extraction.py:140`) |
| Parsed JSON is not an object (list/scalar) | wrapped as `{"result": data}` with an empty confidence map (`src/extraction.py:144`) |
| Field value is not `{"value": ..., "confidence": ...}` | raw value stored; confidence set to `0` (`src/extraction.py:158`) |
| Confidence missing, non-numeric, or outside 0–100 | clamped to `0` (`src/extraction.py:154`) |
| Empty model response (`content` is `None`) | treated as `""` → no JSON → empty fields (`src/extraction.py:93`) |
| Template file missing or broken | `_load_template_fields` returns `[]` → free-form prompt instead of crashing (`src/config.py:59`) |
| Unknown quality tier | handled upstream: the router falls back to a default model (`src/router.py:57`); extraction just receives the resolved `decision.model` |

## API Reference

### `src/extraction.py`

| Symbol | Signature | Location |
|---|---|---|
| `MAX_IMAGE_SIDE` | `int = 2048` | `src/extraction.py:34` |
| `ExtractionResult` | `@dataclass` — `fields: dict`, `confidence_scores: dict[str, int]`, `model: str`, `processing_time: float`, `success: bool`, `error: str \| None` | `src/extraction.py:37` |
| `ExtractionEngine` | class — extracts fields/values from a page image via the routed model | `src/extraction.py:49` |
| `ExtractionEngine.__init__` | `(client=None, max_image_side: int = MAX_IMAGE_SIDE, template_fields: list[str] \| None = None) -> None` | `src/extraction.py:52` |
| `ExtractionEngine.extract` | `(image: Image.Image, decision: RoutingDecision) -> ExtractionResult` | `src/extraction.py:66` |
| `ExtractionEngine._get_client` | `() -> AsyncOpenAI` (internal, lazy `ModelRouter.create_async_client()`) | `src/extraction.py:104` |
| `ExtractionEngine._to_base64_png` | `(image: Image.Image) -> str` (internal) | `src/extraction.py:111` |
| `ExtractionEngine._parse_json_object` | `@staticmethod (raw: str) -> tuple[dict, dict[str, int]]` (internal) | `src/extraction.py:124` |

### `src/prompts.py`

| Symbol | Signature | Location |
|---|---|---|
| `MAX_FIELDS` | `int = 10` (free-form field cap) | `src/prompts.py:20` |
| `build_extraction_prompt` | `(template_fields: list[str] \| None = None) -> str` | `src/prompts.py:44` |
| `EXTRACTION_PROMPT` | `str` — module constant, built once at import | `src/prompts.py:88` |

### Template support (`src/config.py`)

| Symbol | Signature | Location |
|---|---|---|
| `_load_template_fields` | `(path: Path) -> list[str]` — `[]` on missing/broken template | `src/config.py:53` |
| `TEMPLATE_FIELDS` | `list[str]` — field names used to build `EXTRACTION_PROMPT` | `src/config.py:69` |

## Notes & Limitations

- **One API call per page**, `max_tokens=1000` fixed — a very long template field list could truncate the JSON in the reply; the current 8-field template is well within the budget. No retry logic exists; a failed page is recorded and skipped.
- **The prompt is fixed at import time** (`src/prompts.py:88`): `ExtractionEngine.template_fields` is stored on the instance but `extract` always sends the module-level `EXTRACTION_PROMPT`, so editing the template requires a process restart, and passing a different `template_fields` to the constructor does **not** change the prompt sent.
- **Parse failures look like empty extractions, not failures**: when the reply is unparseable, `success` is still `True` and `fields` is empty — only `logger.warning` records the problem.
- **Confidence is model self-reported**, capped at 89 by the prompt; the code only validates the numeric range (0–100) and clamps anything else to `0`.
- **Template values are ignored** — only the key names of `"extracted_fields"` define the schema; empty-string values in `data/Template/test.json` are placeholders.
- `temperature` and other sampling parameters are not set; provider defaults apply. The response is taken from `choices[0].message.content` only.
