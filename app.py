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

from src.doc_extraction import config
from src.doc_extraction.pipeline_graph import run

app = FastAPI(title="DocExtract Demo")

UI_PATH = Path(__file__).resolve().parent / "ui.html"


def _safe_name(name: str) -> str:
    if name != Path(name).name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid file name")
    return name


def _results() -> list[dict]:
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
    return HTMLResponse(UI_PATH.read_text(encoding="utf-8"))


@app.get("/api/files")
def list_files() -> dict:
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        {"name": path.name, "size": path.stat().st_size}
        for path in sorted(config.INPUT_DIR.iterdir())
        if path.is_file() and path.suffix.lower() == ".pdf"
    ]
    return {"files": items}


@app.post("/api/upload")
def upload(files: list[UploadFile] = File(...)) -> dict:
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
    return {"results": _results()}


@app.get("/api/results/{name}")
def result(name: str) -> dict:
    name = _safe_name(name)
    record_path = config.OUTPUT_DIR / name / "result.json"
    if not record_path.is_file():
        raise HTTPException(status_code=404, detail="result not found")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["name"] = name
    return record


@app.get("/api/output/{name}/{file_name}")
def output_file(name: str, file_name: str) -> FileResponse:
    name = _safe_name(name)
    file_name = _safe_name(file_name)
    path = config.OUTPUT_DIR / name / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
