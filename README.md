# Document Extraction Demo

Converts PDF documents into structured JSON through a six-step LangGraph
pipeline. Every step prints the feature it is working on to the terminal.

## Pipeline

```
data/input/*.pdf
   -> Convert     (PDF -> page images)
   -> Enhance     (grayscale, deblur, denoise)
   -> Assess      (0-100 OCR-confidence score + tier)
   -> Route       (quality tier -> vision model)
   -> Extract     (fields + confidence via the vision model)
   -> Output      (enhanced images + result.json)
```

## Model routing

| Tier | Score | Model |
|---|---|---|
| clear | > 80 | `TIER_CLEAR_MODEL` |
| blurry | 50-80 | `TIER_BLURRY_MODEL` |
| very_blurry | < 50 | `TIER_VERY_BLURRY_MODEL` |

## Output

```
data/output/<document>/page-01.png ...   enhanced page images
data/output/<document>/result.json       per-page score, tier, model, fields
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in API_KEY and BASE_URL
```

Requires Poppler (PDF rendering) and Tesseract (OCR) on PATH.

## Run

```
python app.py                     # then open http://127.0.0.1:8000
```

One page with three steps: upload a PDF, process it, and view the extracted
data (page image, quality score, model, fields). The terminal still shows
each feature while the pipeline runs. The "Process all" button handles every
PDF in `data/input` at once.

All configuration (gateway URL, API key, model IDs, tier mapping, paths)
lives in `.env`.
