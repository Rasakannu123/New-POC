# Document Extraction POC

Image quality assessment and model-selection pipeline for document
extraction. Each PDF page is converted, enhanced, scored, routed to a
vision model appropriate to its quality, and extracted into structured
JSON. Console logging only - no UI.

## Pipeline

```
data/input/*.pdf
   -> Convert      (PDF -> page images, 300 DPI)
   -> Preprocess   (grayscale, adaptive deblur, denoise, deskew, CLAHE)
   -> Assess       (0-100 score: 40% focus + 60% OCR confidence)
   -> Route        (quality tier -> vision model)
   -> Extract      (top fields/values + confidence)
   -> data/output/ (<doc>_<page>_q<score>.png / .json)
```

## Routing

| Tier | Score | Model |
|---|---|---|
| clear | > 80 | `mimo-v2.5` |
| blurry | 50-80 | `minimax-m3` |
| very_blurry | < 50 | `qwen3.8-max` |

## Project structure

```
New-POC/
  main.py                     entry point
  requirements.txt
  pyproject.toml
  .env                        all secrets + settings (gitignored)
  .env.example                template
  data/
    input/                    drop PDFs here
    output/                   generated png + json
  src/
    doc_extraction/
      config.py               loads .env
      pipeline.py             orchestrator
      layers/
        conversion.py         PDF -> images
        preprocessing.py      OpenCV enhancement
        quality.py            score + tier
        router.py             tier -> model
        extraction.py         vision model -> fields
  tests/
```

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then fill in API_KEY and BASE_URL
```

Requires Poppler (PDF rendering) and Tesseract (OCR confidence) on PATH,
or set `POPPLER_PATH` in `.env`.

## Run

```
python main.py
```

All configuration (gateway URL, API key, model IDs, tier mapping, DPI,
paths) lives in `.env`.