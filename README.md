# Document Extraction Demo

Converts PDF documents into structured JSON through a six-step LangGraph
pipeline. Every step prints the feature it is working on to the terminal.

## Pipeline

```
data/input/*.pdf
   -> Convert     (PDF -> page images)
   -> Enhance     (grayscale, deblur, denoise, deskew, CLAHE)
   -> Assess      (0-100 OCR-confidence score + tier)
   -> Route       (quality tier -> vision model)
   -> Extract     (fields + confidence via the vision model)
   -> Output      (enhanced images + result.json)
```

## Model routing

| Tier | Score | Model |
|---|---|---|
| clear | > 80 | `IMAGE_MODEL_SMALL` |
| blurry | 50-80 | `IMAGE_MODEL_MEDIUM` |
| very_blurry | < 50 | `IMAGE_MODEL_LARGE` |

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

Requires Poppler (PDF rendering) and Tesseract (OCR) on PATH,
or set `POPPLER_PATH` in `.env`.

## Run

```
python main.py                    # every PDF in data/input
python main.py path/to/file.pdf   # one specific PDF
```

All configuration (gateway URL, API key, model IDs, tier mapping, DPI,
paths) lives in `.env`.
