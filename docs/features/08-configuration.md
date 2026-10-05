# Feature 8 — Configuration & Environment (`src/config.py`)

> Every endpoint, key, model identifier and pipeline setting lives in `.env`. No secret is hard-coded.

## Purpose

`src/config.py` is the single source of truth for all runtime settings and secrets. It loads the project `.env` file once at import time and exposes every setting as a module-level constant, so the rest of the pipeline never reads `os.environ` directly and no API key, endpoint, or model name is hard-coded in source. A real `.env` file exists in the project root; it mirrors [`.env.example`](../../.env.example) but carries the actual secrets and is not documented here.

## How It Works

**Loading mechanism.** `PROJECT_ROOT` is resolved from the module's own location — `Path(__file__).resolve().parents[1]` ([src/config.py:16](../../src/config.py#L16)) — i.e. the parent of `src/`, so the `.env` file is always found at the repository root no matter which directory the process starts from. `load_dotenv(PROJECT_ROOT / ".env")` ([src/config.py:17](../../src/config.py#L17)) then loads it via `python-dotenv` as a plain import-time side effect. `load_dotenv` is non-strict: if `.env` is missing or unreadable, loading silently does nothing and every variable falls back to its code default.

**Value lookup.** Every setting is read with `os.getenv(name, default)`. Two parsing details matter:

- `DPI` and `OCR_CONCURRENCY` are wrapped in `int()` ([src/config.py:37](../../src/config.py#L37), [src/config.py:40](../../src/config.py#L40)) — a non-numeric value raises `ValueError` at import.
- `POPPLER_PATH = os.getenv("POPPLER_PATH") or None` ([src/config.py:39](../../src/config.py#L39)) — an empty string becomes `None`, so `pdf2image` falls back to searching the system `PATH`.
- `INPUT_DIR` / `OUTPUT_DIR` ([src/config.py:42](../../src/config.py#L42)-[43](../../src/config.py#L43)) use the same `or` trick: an empty env value falls back to `PROJECT_ROOT/data/input` and `PROJECT_ROOT/data/output`. (These two keys are honored by the code but are not listed in `.env.example`.)

**`_load_template_fields` fallback.** The helper at [src/config.py:53](../../src/config.py#L53)-[66](../../src/config.py#L66) reads the extraction template JSON and returns the list of field names. It never raises:

- `OSError` (missing/unreadable file) or `json.JSONDecodeError` (broken JSON) → returns `[]`, so extraction falls back to free-form mode instead of crashing ([src/config.py:57](../../src/config.py#L57)-[60](../../src/config.py#L60)).
- If the top level is a `dict`, its `extracted_fields` block is used when present, otherwise the dict's own keys ([src/config.py:61](../../src/config.py#L61)).
- If the block is a `dict`, its keys become the field names; if it is a `list`, its items are stringified ([src/config.py:62](../../src/config.py#L62)-[65](../../src/config.py#L65)).
- Any other shape → `[]`.

The result is captured once into `TEMPLATE_FIELDS` ([src/config.py:69](../../src/config.py#L69)).

**`OMP_THREAD_LIMIT`.** The last statement, `os.environ.setdefault("OMP_THREAD_LIMIT", "1")` ([src/config.py:71](../../src/config.py#L71)), caps OpenMP-backed thread pools (e.g. OpenCV) at one thread — but only if the variable is not already set, so an explicit value in the environment wins. This keeps native thread counts low while `OCR_CONCURRENCY` controls parallelism at the Python level.

## Environment Variables Reference

Complete list of keys in [`.env.example`](../../.env.example), with defaults taken from the code:

| Key | Purpose | Default (from code) | Required / Optional |
|---|---|---|---|
| `API_KEY` | API key for the OpenAI-compatible gateway used by the extraction step | `""` (empty string) | Required at runtime — no validation in `config.py`; extraction calls fail without it |
| `BASE_URL` | Base URL of the OpenAI-compatible gateway (`.env.example` suggests `https://api.xkiro.com/v1`) | `""` (empty string) | Required at runtime — no validation in `config.py` |
| `IMAGE_MODEL_LARGE` | Vision model identifier for the large tier | `mistralai/mistral-large-2512` | Optional |
| `IMAGE_MODEL_MEDIUM` | Vision model identifier for the medium tier | `mistralai/mistral-medium-3.5` | Optional |
| `IMAGE_MODEL_SMALL` | Vision model identifier for the small tier | `mistralai/mistral-small-2603` | Optional |
| `TIER_CLEAR_MODEL` | Extraction model for the `clear` quality tier | value of `IMAGE_MODEL_SMALL` | Optional |
| `TIER_BLURRY_MODEL` | Extraction model for the `blurry` quality tier | value of `IMAGE_MODEL_MEDIUM` | Optional |
| `TIER_VERY_BLURRY_MODEL` | Extraction model for the `very_blurry` quality tier | value of `IMAGE_MODEL_LARGE` | Optional |
| `DPI` | Resolution for PDF → image rendering | `300` | Optional (`int`; non-numeric raises `ValueError` at import) |
| `IMAGE_FORMAT` | Image output format | `png` | Optional |
| `POPPLER_PATH` | Folder containing the Poppler binaries for `pdf2image`; empty = search system `PATH` | `None` | Optional |
| `OCR_CONCURRENCY` | Number of parallel OCR-confidence calls | `4` | Optional (`int`; non-numeric raises `ValueError` at import) |
| `TEMPLATE_PATH` | Path to the extraction template JSON | `PROJECT_ROOT/data/Template/test.json` | Optional (missing/broken file → free-form extraction) |

Additional keys read by the code but absent from `.env.example` (both default as shown when unset or empty):

| Key | Purpose | Default (from code) | Required / Optional |
|---|---|---|---|
| `INPUT_DIR` | Directory scanned for input PDFs | `PROJECT_ROOT/data/input` | Optional |
| `OUTPUT_DIR` | Directory for enhanced images and result JSON | `PROJECT_ROOT/data/output` | Optional |

Note: when a relative path is supplied via `TEMPLATE_PATH`, `INPUT_DIR`, or `OUTPUT_DIR`, it is kept as-is and resolves against the process working directory at use time; the built-in defaults are absolute under `PROJECT_ROOT`.

## Model Configuration

Three vision-model identifiers are configurable ([src/config.py:25](../../src/config.py#L25)-[27](../../src/config.py#L27)):

| Constant | Env key | Built-in default |
|---|---|---|
| `MODEL_IMAGE_LARGE` | `IMAGE_MODEL_LARGE` | `mistralai/mistral-large-2512` |
| `MODEL_IMAGE_MEDIUM` | `IMAGE_MODEL_MEDIUM` | `mistralai/mistral-medium-3.5` |
| `MODEL_IMAGE_SMALL` | `IMAGE_MODEL_SMALL` | `mistralai/mistral-small-2603` |

`TIER_MODEL_MAP` ([src/config.py:30](../../src/config.py#L30)-[34](../../src/config.py#L34)) maps the quality router's tiers to extraction models:

| Tier | Env key | Default |
|---|---|---|
| `clear` | `TIER_CLEAR_MODEL` | `MODEL_IMAGE_SMALL` (i.e. `IMAGE_MODEL_SMALL` or `mistralai/mistral-small-2603`) |
| `blurry` | `TIER_BLURRY_MODEL` | `MODEL_IMAGE_MEDIUM` (i.e. `IMAGE_MODEL_MEDIUM` or `mistralai/mistral-medium-3.5`) |
| `very_blurry` | `TIER_VERY_BLURRY_MODEL` | `MODEL_IMAGE_LARGE` (i.e. `IMAGE_MODEL_LARGE` or `mistralai/mistral-large-2512`) |

The fallback is two-level: each `TIER_*_MODEL` defaults to the corresponding `IMAGE_MODEL_*` constant, which itself defaults to a built-in identifier. Changing `IMAGE_MODEL_SMALL` therefore also changes the `clear` tier unless `TIER_CLEAR_MODEL` is set explicitly.

## Template Configuration

`TEMPLATE_PATH` ([src/config.py:48](../../src/config.py#L48)-[50](../../src/config.py#L50)) points at an optional JSON schema that locks extraction to a fixed set of fields. The default template [`data/Template/test.json`](../../data/Template/test.json) looks like:

```json
{
  "extracted_fields": {
    "document_no": "",
    "dete": "",
    "buyer": "",
    "buyer-trn": "",
    "seller": "",
    "seller-trn": "",
    "dn": "",
    "sub total": ""
  }
}
```

`_load_template_fields` turns this into `TEMPLATE_FIELDS = ["document_no", "dete", "buyer", "buyer-trn", "seller", "seller-trn", "dn", "sub total"]` — the keys of `extracted_fields`; the values in the template are irrelevant placeholders. If the file is missing or broken, `TEMPLATE_FIELDS` is `[]` and extraction runs in free-form mode (see Error Handling & Edge Cases).

## External Dependencies

**Python packages** ([`requirements.txt`](../../requirements.txt), mirrored in the `pyproject.toml` dependency list with `requires-python >= 3.11`):

| Package | Version floor | Used for |
|---|---|---|
| `python-dotenv` | `>=1.0.0` | Loading `.env` in `src/config.py` |
| `pdf2image` | `>=1.17.0` | PDF → page images (requires the Poppler system binary) |
| `Pillow` | `>=10.0.0` | Image objects throughout the pipeline |
| `opencv-python` | `>=4.8.0` | Image enhancement |
| `numpy` | `>=1.24.0` | Array math in quality scoring |
| `pytesseract` | `>=0.3.10` | OCR-confidence quality metric (requires the Tesseract system binary) |
| `openai` | `>=1.0.0` | OpenAI-compatible gateway client for extraction |
| `langgraph` | `>=0.2.0` | The six-step pipeline graph |
| `fastapi` | `>=0.110.0` | Web UI backend (`app.py`) |
| `uvicorn` | `>=0.29.0` | ASGI server for the web UI |
| `python-multipart` | `>=0.0.9` | File uploads in the web UI |

**System binaries:**

- **Poppler** — required by `pdf2image` for PDF rendering. Located via `POPPLER_PATH` (the folder containing the binaries, e.g. `C:\poppler-26.02.0\Library\bin`) or the system `PATH`. If Poppler is missing, conversion fails gracefully with an install hint (see Error Handling).
- **Tesseract OCR** — optional. Only needed for the OCR-confidence quality metric: `src/quality.py` enables it when `pytesseract` is importable *and* `shutil.which("tesseract")` finds the binary on `PATH` ([src/quality.py:146](../../src/quality.py#L146)-[164](../../src/quality.py#L164)). Without it the pipeline still runs; the OCR-confidence signal degrades to `0`.

## Error Handling & Edge Cases

| Situation | Behavior |
|---|---|
| `.env` missing or unreadable | `load_dotenv` is non-strict — import succeeds and every variable falls back to its code default (`API_KEY`/`BASE_URL` become `""`). No error is raised by `config.py`. |
| Non-numeric `DPI` or `OCR_CONCURRENCY` | `int()` raises `ValueError` at import time — the only way `config.py` itself crashes. The message is the raw Python one; no custom validation exists. |
| Missing template file | `OSError` is caught in `_load_template_fields` → `TEMPLATE_FIELDS = []` → free-form extraction ([src/config.py:57](../../src/config.py#L57)-[60](../../src/config.py#L60)). |
| Broken template JSON | `json.JSONDecodeError` is caught the same way → `[]` → free-form extraction. |
| Template that is neither dict nor list | Returns `[]` → free-form extraction. |
| Template dict without `extracted_fields` | The dict's own top-level keys become the field names ([src/config.py:61](../../src/config.py#L61)). |
| Empty `POPPLER_PATH` | Becomes `None`; `pdf2image` searches `PATH`. If Poppler is still missing, conversion catches `PDFInfoNotInstalledError` and returns a `result.error` with install instructions instead of raising ([src/conversion.py:72](../../src/conversion.py#L72)-[75](../../src/conversion.py#L75)). |
| `pytesseract` not installed or `tesseract` binary not on `PATH` | Warning is logged and the OCR-confidence metric returns `0`; the rest of the pipeline is unaffected ([src/quality.py:146](../../src/quality.py#L146)-[164](../../src/quality.py#L164)). |
| `OMP_THREAD_LIMIT` already set in the environment | `setdefault` leaves the existing value untouched ([src/config.py:71](../../src/config.py#L71)). |
| Empty `INPUT_DIR` / `OUTPUT_DIR` / `TEMPLATE_PATH` | Falls back to the built-in default paths under `PROJECT_ROOT`. |

## API Reference

Module-level constants and functions exposed by `src/config.py` (all resolved at import time):

| Name | Kind | Location | Description |
|---|---|---|---|
| `PROJECT_ROOT` | `Path` | [src/config.py:16](../../src/config.py#L16) | Repository root, resolved as the parent of `src/` regardless of CWD. |
| `API_KEY` | `str` | [src/config.py:21](../../src/config.py#L21) | Gateway API key from `API_KEY`; default `""`. |
| `BASE_URL` | `str` | [src/config.py:22](../../src/config.py#L22) | Gateway base URL from `BASE_URL`; default `""`. |
| `MODEL_IMAGE_LARGE` | `str` | [src/config.py:25](../../src/config.py#L25) | Vision model id from `IMAGE_MODEL_LARGE`. |
| `MODEL_IMAGE_MEDIUM` | `str` | [src/config.py:26](../../src/config.py#L26) | Vision model id from `IMAGE_MODEL_MEDIUM`. |
| `MODEL_IMAGE_SMALL` | `str` | [src/config.py:27](../../src/config.py#L27) | Vision model id from `IMAGE_MODEL_SMALL`. |
| `TIER_MODEL_MAP` | `dict[str, str]` | [src/config.py:30](../../src/config.py#L30) | Maps `clear` / `blurry` / `very_blurry` quality tiers to model ids (`TIER_*_MODEL`, defaulting to the `IMAGE_MODEL_*` values). |
| `DPI` | `int` | [src/config.py:37](../../src/config.py#L37) | PDF render DPI from `DPI`; default `300`. |
| `IMAGE_FORMAT` | `str` | [src/config.py:38](../../src/config.py#L38) | Image format from `IMAGE_FORMAT`; default `"png"`. |
| `POPPLER_PATH` | `str \| None` | [src/config.py:39](../../src/config.py#L39) | Poppler binary folder from `POPPLER_PATH`; empty → `None`. |
| `OCR_CONCURRENCY` | `int` | [src/config.py:40](../../src/config.py#L40) | Parallel OCR calls from `OCR_CONCURRENCY`; default `4`. |
| `INPUT_DIR` | `Path` | [src/config.py:42](../../src/config.py#L42) | Input PDF directory from `INPUT_DIR`; default `PROJECT_ROOT/data/input`. |
| `OUTPUT_DIR` | `Path` | [src/config.py:43](../../src/config.py#L43) | Output directory from `OUTPUT_DIR`; default `PROJECT_ROOT/data/output`. |
| `TEMPLATE_PATH` | `Path` | [src/config.py:48](../../src/config.py#L48) | Template JSON path from `TEMPLATE_PATH`; default `PROJECT_ROOT/data/Template/test.json`. |
| `_load_template_fields(path)` | function | [src/config.py:53](../../src/config.py#L53) | Returns the template's field names as `list[str]`; `[]` on missing/broken file or unrecognized shape. |
| `TEMPLATE_FIELDS` | `list[str]` | [src/config.py:69](../../src/config.py#L69) | Field names loaded from `TEMPLATE_PATH` at import; empty list means free-form extraction. |
| `OMP_THREAD_LIMIT` (env side effect) | — | [src/config.py:71](../../src/config.py#L71) | Set to `"1"` via `os.environ.setdefault` unless already present. |

## Notes & Limitations

- All configuration is resolved **once at import time**; editing `.env` has no effect until the process restarts.
- There is no validation of `API_KEY` or `BASE_URL` — empty or wrong values only surface when the extraction step tries to call the gateway.
- A typo in `DPI` or `OCR_CONCURRENCY` crashes at import with a bare `ValueError` from `int()`; no friendly message is produced.
- The `.env` file is looked up at `PROJECT_ROOT` (the repository root), not the current working directory — a `.env` next to a script run from elsewhere will be ignored.
- `TEMPLATE_PATH`, `INPUT_DIR`, and `OUTPUT_DIR`, when set to relative paths, resolve against the process working directory, not `PROJECT_ROOT` — run the app from the repository root to keep the `.env.example` values valid.
- `TEMPLATE_FIELDS` is computed eagerly at import even if the template is never used, so a broken template silently degrades to free-form mode with no log message from `config.py` itself.
- `.env.example` lists 13 keys; `INPUT_DIR` and `OUTPUT_DIR` are also honored by the code but undocumented there.
