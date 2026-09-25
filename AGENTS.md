# AGENTS.md

## Project

Document extraction demo - PDF to structured JSON via a LangGraph pipeline.
Entry point: `main.py` -> `src/doc_extraction/pipeline_graph.py`.

## Layout

- `src/doc_extraction/config.py` - loads all settings/secrets from `.env`.
- `src/doc_extraction/layers/` - one module per pipeline feature.
- `data/input/` - input PDFs; `data/output/` - enhanced images + result JSON.

## Commands

- Install: `pip install -r requirements.txt`
- Run: `python main.py` (all PDFs in `data/input`) or `python main.py <file.pdf>`
- Test: `pytest`
- Lint: `ruff check .` (if installed)

## Conventions

- No secrets in code - everything goes through `.env`.
- Do not add comments unless asked.
