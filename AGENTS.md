# AGENTS.md

## Project

Document Extraction POC - image quality assessment and model-selection
pipeline. Entry point: `main.py` -> `src/doc_extraction/pipeline.py`.

## Layout

- `src/doc_extraction/config.py` - loads all settings/secrets from `.env`.
- `src/doc_extraction/layers/` - one module per pipeline stage.
- `data/input/` - input PDFs; `data/output/` - generated files.

## Commands

- Install: `pip install -r requirements.txt`
- Run: `python main.py`
- Test: `pytest`
- Lint: `ruff check .` (if installed)

## Conventions

- No secrets in code - everything goes through `.env`.
- Do not add comments unless asked.