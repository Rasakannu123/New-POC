"""
Minimal web UI for the demo: upload a PDF, run the pipeline, view results.

The pipeline itself keeps printing the current feature to this terminal.

Run:
    python app.py   ->  http://127.0.0.1:8000
"""

from __future__ import annotations

import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from src import config
from src.pipeline_graph import run

app = FastAPI(title="DocExtract Demo")

UI_PATH = Path(__file__).resolve().parent / "ui.html"


def _safe_name(name: str) -> str:
    """Reject path tricks (../, folders) because browser-supplied names are
    used directly in file paths - this is the one security check the UI needs."""
    if name != Path(name).name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid file name")
    return name


def _results() -> list[dict]:
    """Collects every result.json so the data view can list processed documents
    without knowing their names in advance."""
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for directory in sorted(config.OUTPUT_DIR.iterdir()):
        record_path = directory / "result.json"
        if directory.is_dir() and record_path.is_file():
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["name"] = directory.name
            results.append(record)
    return results


@app.get("/")
def index() -> HTMLResponse:
    """Serves the single UI page - everything the user sees lives in ui.html."""
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/api/files")
def list_files() -> dict:
    """Shows the PDFs in data/input so the user can see what can be processed
    and pick one."""
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        {"name": path.name, "size": path.stat().st_size}
        for path in sorted(config.INPUT_DIR.iterdir())
        if path.is_file() and path.suffix.lower() == ".pdf"
    ]
    return {"files": items}


@app.post("/api/upload")
def upload(files: list[UploadFile] = File(...)) -> dict:
    """Stores uploaded PDFs in data/input, the same folder the CLI uses, so
    web-uploaded and hand-copied documents behave identically."""
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for upload_file in files:
        name = _safe_name(Path(upload_file.filename or "").name)
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail=f"'{name}' is not a PDF")
        (config.INPUT_DIR / name).write_bytes(upload_file.file.read())
        saved.append(name)
    return {"saved": saved}


@app.post("/api/process")
def process(file: str | None = None) -> dict:
    """Runs the pipeline (one file or everything) and returns the fresh results
    so the page can show data immediately - the terminal shows the features
    while this request waits for the run to finish."""
    if file:
        pdf_path = config.INPUT_DIR / _safe_name(file)
        if not pdf_path.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        exit_code = run([pdf_path])
    else:
        exit_code = run()
    return {"exit_code": exit_code, "results": _results()}


@app.get("/api/results")
def results() -> dict:
    """Lists processed documents for the data view's document buttons."""
    return {"results": _results()}


@app.get("/api/results/{name}")
def result(name: str) -> dict:
    """Returns one document's full extraction record (fields, scores, models)
    so the data view can render the per-page tables."""
    name = _safe_name(name)
    record_path = config.OUTPUT_DIR / name / "result.json"
    if not record_path.is_file():
        raise HTTPException(status_code=404, detail="result not found")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["name"] = name
    return record


@app.get("/api/output/{name}/{file_name}")
def output_file(name: str, file_name: str) -> FileResponse:
    """Serves the enhanced page images so the data view can show the page
    next to its extracted fields."""
    name = _safe_name(name)
    file_name = _safe_name(file_name)
    path = config.OUTPUT_DIR / name / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
