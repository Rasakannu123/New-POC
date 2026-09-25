# AGENTS.md

## Project

Document extraction demo - PDF to structured JSON via a LangGraph pipeline.
Entry point: `main.py` -> `src/pipeline_graph.py`.

## Layout

- `src/config.py` - loads all settings/secrets from `.env`.
- `src/` - one flat module per pipeline feature (no subfolders).
- `app.py` + `ui.html` - one-page web UI (upload, process, data view).
- `data/input/` - input PDFs; `data/output/` - enhanced images + result JSON.

## Commands

- Install: `pip install -r requirements.txt`
- Run: `python main.py` (all PDFs in `data/input`) or `python main.py <file.pdf>`
- Web UI: `python app.py` (http://127.0.0.1:8000)
- Lint: `ruff check .` (if installed)

## Conventions

- No secrets in code - everything goes through `.env`.
- Do not add comments unless asked.
