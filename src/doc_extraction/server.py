"""
Local API server for the review UI (ui/).

Exposes the pipeline folders (input / output / skip / Manual-Review) and
the extraction template to the React app. Run from the project root:

    uvicorn src.doc_extraction.server:app --port 8000
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.doc_extraction import config
from src.doc_extraction.pipeline import run as run_pipeline

app = FastAPI(title="DocExtract Console API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BUCKETS: dict[str, Path] = {
    "input": config.INPUT_DIR,
    "output": config.OUTPUT_DIR,
    "skip": config.SKIP_DIR,
    "review": config.MANUAL_REVIEW_DIR,
}


def _bucket_dir(bucket: str) -> Path:
    directory = BUCKETS.get(bucket)
    if directory is None:
        raise HTTPException(status_code=404, detail=f"unknown bucket '{bucket}'")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_name(name: str) -> str:
    if name != Path(name).name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid file name")
    return name


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/buckets/{bucket}")
def list_bucket(bucket: str) -> dict:
    directory = _bucket_dir(bucket)

    if bucket == "input":
        items = [
            {"name": path.name, "size": path.stat().st_size}
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() == ".pdf"
        ]
        return {"bucket": bucket, "items": items}

    items = []
    for image_path in sorted(directory.glob(f"*.{config.IMAGE_FORMAT}")):
        record_path = image_path.with_suffix(".json")
        record = {}
        if record_path.is_file():
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                record = {}
        items.append(
            {"name": image_path.stem, "image": image_path.name, "record": record}
        )
    return {"bucket": bucket, "items": items}


@app.get("/api/image/{bucket}/{name}")
def get_image(bucket: str, name: str) -> FileResponse:
    name = _safe_name(name)
    path = _bucket_dir(bucket) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path, media_type=f"image/{config.IMAGE_FORMAT}")


@app.get("/api/record/{bucket}/{name}")
def get_record(bucket: str, name: str) -> dict:
    name = _safe_name(name)
    path = _bucket_dir(bucket) / f"{name}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="record not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/upload")
def upload(files: list[UploadFile] = File(...)) -> dict:
    directory = _bucket_dir("input")
    saved = []
    for upload_file in files:
        name = _safe_name(Path(upload_file.filename or "").name)
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=422, detail=f"'{name}' is not a PDF")
        (directory / name).write_bytes(upload_file.file.read())
        saved.append(name)
    return {"saved": saved}


@app.get("/api/template")
def get_template() -> dict:
    if not config.TEMPLATE_PATH.is_file():
        return {"extracted_fields": {}, "no_need_page": {}}
    return json.loads(config.TEMPLATE_PATH.read_text(encoding="utf-8"))


_process_state: dict = {
    "running": False,
    "last_exit_code": None,
    "error": None,
    "finished_at": None,
}
_process_lock = threading.Lock()


def _process_worker() -> None:
    try:
        exit_code = run_pipeline()
        _process_state["last_exit_code"] = exit_code
        _process_state["error"] = None
    except Exception as exc:
        _process_state["last_exit_code"] = 1
        _process_state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _process_state["finished_at"] = time.time()
        _process_state["running"] = False


@app.post("/api/process")
def start_process() -> dict:
    with _process_lock:
        if _process_state["running"]:
            raise HTTPException(status_code=409, detail="pipeline is already running")
        _process_state["running"] = True
        _process_state["error"] = None
    threading.Thread(target=_process_worker, daemon=True).start()
    return {"started": True}


@app.get("/api/process/status")
def process_status() -> dict:
    with _process_lock:
        return dict(_process_state)


@app.put("/api/template")
def put_template(data: dict) -> dict:
    extracted = data.get("extracted_fields")
    no_need = data.get("no_need_page")
    if not isinstance(extracted, dict) or not isinstance(no_need, dict):
        raise HTTPException(
            status_code=422,
            detail="expected 'extracted_fields' and 'no_need_page' objects",
        )
    payload = {
        "extracted_fields": {str(key): "" for key in extracted},
        "no_need_page": {str(key): "" for key in no_need},
    }
    config.TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.TEMPLATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload
