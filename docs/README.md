# Document Extraction Demo — Documentation

A document-extraction demo that converts PDF documents into structured JSON
through a six-step [LangGraph](https://github.com/langchain-ai/langgraph)
pipeline. Every step prints the feature it is working on to the terminal, and
the same pipeline powers both the CLI (`main.py`) and the one-page web UI
(`app.py`).

## What it does

```
data/input/*.pdf
   │
   ▼
┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌──────────┐   ┌────────┐
│ convert │──▶│ enhance │──▶│ assess  │──▶│  route  │──▶│ extract  │──▶│ output │──▶ END
└─────────┘   └─────────┘   └─────────┘   └─────────┘   └──────────┘   └────────┘
 PDF →          grayscale,    0–100 score   tier →       vision model   enhanced
 page           deblur,       + quality     extraction   fields +       images +
 images         denoise,      tier          model        confidence     result.json
                deskew,       (clear /                    per page
                CLAHE         blurry /
                              very_blurry)
```

One PDF = one LangGraph run. The graph has six nodes — one per feature —
wired linearly: `START → convert → enhance → assess → route → extract →
output → END` (see `src/pipeline_graph.py:191`).

## Main features

| # | Feature | Module | Documentation |
|---|---------|--------|---------------|
| 1 | PDF-to-Images conversion | `src/conversion.py` | [01-pdf-to-image-conversion.md](features/01-pdf-to-image-conversion.md) |
| 2 | Image enhancement | `src/preprocessing.py` | [02-image-enhancement.md](features/02-image-enhancement.md) |
| 3 | Quality assessment | `src/quality.py` | [03-quality-assessment.md](features/03-quality-assessment.md) |
| 4 | Model router | `src/router.py` | [04-model-router.md](features/04-model-router.md) |
| 5 | Data extraction | `src/extraction.py`, `src/prompts.py` | [05-data-extraction.md](features/05-data-extraction.md) |
| 6 | JSON output | `src/pipeline_graph.py` | [06-json-output.md](features/06-json-output.md) |
| 7 | Web UI | `app.py`, `ui.html` | [07-web-ui.md](features/07-web-ui.md) |
| 8 | Configuration & environment | `src/config.py`, `.env` | [08-configuration.md](features/08-configuration.md) |

## How it works — end to end

### 1. Entry points

There are two ways to run the pipeline, and both share the exact same graph:

- **CLI** — `main.py` collects PDF paths from the command line (or falls back
  to every PDF in `data/input`) and calls `run()` in `src/pipeline_graph.py:212`.
  The shell exit code is `0` when every document succeeded, `1` otherwise.
- **Web UI** — `python app.py` serves `ui.html` at `http://127.0.0.1:8000`.
  Upload → process → view extracted data. The terminal still shows each
  feature while the pipeline runs.

### 2. Pipeline state

All six nodes communicate through one small `PipelineState` TypedDict
(`src/pipeline_graph.py:45`): `pdf_path`, `images`, `enhanced`,
`assessments`, `routing`, `extractions`, `output_json`, `error`. Each node
returns only the keys it changes, so the state stays small and easy to follow.

### 3. The six nodes

1. **convert** (`convert_node`) — renders the PDF to page images at
   `DPI` (default 300) via the PDF-to-image layer. A broken PDF is recorded
   in `state["error"]` and reported at the end of the run instead of crashing.
2. **enhance** (`enhance_node`) — cleans every page image (grayscale,
   deblur, denoise, deskew, CLAHE) so OCR and the vision model read it as
   clearly as possible.
3. **assess** (`assess_node`) — scores every enhanced page **0–100** and
   assigns a quality tier. Scores are printed because they explain every
   later routing choice.
4. **route** (`route_node`) — maps each page's tier to an extraction model,
   so clear pages use the cheap model and only hard pages pay for the strong
   one:

   | Tier | Score | Model |
   |---|---|---|
   | `clear` | > 80 | `IMAGE_MODEL_SMALL` |
   | `blurry` | 50–80 | `IMAGE_MODEL_MEDIUM` |
   | `very_blurry` | < 50 | `IMAGE_MODEL_LARGE` |

5. **extract** (`extract_node`) — the vision-model call that turns each page
   image into `extracted_fields` + `field_confidence_scores`; one entry per
   page so results stay page-aligned.
6. **output** (`output_node`) — writes the enhanced page images and
   `result.json` per document. Nothing is written when nothing was extracted.

### 4. Output

```
data/output/<document>/
   page-01.png ...        enhanced page images
   result.json            per-page score, tier, model, fields
```

`result.json` merges, per page: `page`, `image`, `quality_score`,
`quality_tier`, `model`, `extracted_fields`, `field_confidence_scores`,
`success`, `error`. This file is the final data the web UI displays.

## Project layout

```
main.py                  CLI entry point
app.py + ui.html         one-page web UI (upload, process, data view)
src/
   config.py             all settings/secrets from .env
   prompts.py            all AI model prompts in one place
   pipeline_graph.py     LangGraph graph: 6 nodes + state + run()
   conversion.py         Feature 1 - PDF-to-images converter
   preprocessing.py      Feature 2 - image enhancement
   quality.py            Feature 3 - quality assessment
   router.py             Feature 4 - model router
   extraction.py         Feature 5 - data extraction
data/
   input/                input PDFs
   output/               enhanced images + result.json per document
   Template/test.json    optional extraction template (fixed field set)
docs/                     this documentation
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then fill in API_KEY and BASE_URL
```

Requires **Poppler** (PDF rendering) and **Tesseract** (OCR) on PATH,
or set `POPPLER_PATH` in `.env`. See
[08-configuration.md](features/08-configuration.md) for the full
environment-variable reference.

## Run

```bash
python main.py                    # every PDF in data/input
python main.py path/to/file.pdf   # one specific PDF
python app.py                     # web UI at http://127.0.0.1:8000
```

## Design principles

- **One feature per module** — `src/` is flat; every pipeline feature lives
  in its own module and its own graph node.
- **No secrets in code** — everything (gateway URL, API key, model IDs, tier
  mapping, DPI, paths) goes through `.env` via `src/config.py`.
- **Cost-aware extraction** — quality-driven model routing sends clear pages
  to the small model and reserves the large model for hard pages.
- **Page-aligned results** — every per-page record carries its score, tier,
  model and fields together, so the UI can show the full story per page.
