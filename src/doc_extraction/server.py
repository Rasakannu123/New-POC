"""
Local API server for the review UI (ui/).

Exposes the pipeline folders (input / output / skip / Manual-Review) and
the extraction template to the React app. Run from the project root:

    uvicorn src.doc_extraction.server:app --port 8000
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from src.doc_extraction import config
from src.doc_extraction.cost import aggregate_records
from src.doc_extraction.pipeline import run as run_pipeline
from src.doc_extraction.pipeline_graph import (
    RUN_EVENTS,
    clear_run_registry,
    list_runs,
    load_checkpoint_history,
    read_run,
)

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


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
            {
                "kind": "page",
                "name": image_path.stem,
                "image": image_path.name,
                "record": record,
            }
        )

    for subdirectory in sorted(path for path in directory.iterdir() if path.is_dir()):
        for pdf_path in sorted(subdirectory.glob("*.pdf")):
            record_path = pdf_path.with_suffix(".json")
            record = {}
            if record_path.is_file():
                try:
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    record = {}
            items.append(
                {
                    "kind": "document",
                    "name": f"{subdirectory.name}/{pdf_path.stem}",
                    "pdf": f"{subdirectory.name}/{pdf_path.name}",
                    "record": record,
                }
            )
    return {"bucket": bucket, "items": items}


@app.delete("/api/input/{name}")
def delete_input_file(name: str) -> dict:
    name = _safe_name(name)
    path = _bucket_dir("input") / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    path.unlink()
    return {"deleted": name}


@app.delete("/api/document/{bucket}/{stem}")
def delete_document(bucket: str, stem: str) -> dict:
    stem = _safe_name(stem)
    directory = _bucket_dir(bucket) / stem
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="document not found")
    shutil.rmtree(directory)
    return {"deleted": stem}


@app.delete("/api/page/{bucket}/{name}")
def delete_page(bucket: str, name: str) -> dict:
    name = _safe_name(name)
    directory = _bucket_dir(bucket)
    deleted = []
    for suffix in (f".{config.IMAGE_FORMAT}", ".json"):
        path = directory / f"{name}{suffix}"
        if path.is_file():
            path.unlink()
            deleted.append(path.name)
    if not deleted:
        raise HTTPException(status_code=404, detail="page not found")
    return {"deleted": deleted}


@app.delete("/api/clear/{bucket}")
def clear_bucket(bucket: str) -> dict:
    directory = _bucket_dir(bucket)
    removed = 0

    for path in list(directory.iterdir()):
        if path.is_dir():
            shutil.rmtree(path)
            removed += 1
            continue
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if bucket == "input":
            if suffix == ".pdf":
                path.unlink()
                removed += 1
        elif suffix in {f".{config.IMAGE_FORMAT}", ".json", ".pdf"}:
            path.unlink()
            removed += 1

    return {"removed": removed}


@app.get("/api/costs")
def get_costs() -> dict:
    records: list[dict] = []

    output = _bucket_dir("output")
    for subdirectory in sorted(path for path in output.iterdir() if path.is_dir()):
        for record_path in sorted(subdirectory.glob("*.json")):
            record = _read_json(record_path)
            if record:
                records.append(record)

    review = _bucket_dir("review")
    for record_path in sorted(review.glob("*.json")):
        record = _read_json(record_path)
        if record and "cost" in record:
            records.append(record)

    return aggregate_records(records)


@app.get("/api/pdf/{bucket}/{pdf_path:path}")
def get_pdf(bucket: str, pdf_path: str) -> FileResponse:
    directory = _bucket_dir(bucket).resolve()
    candidate = (directory / pdf_path).resolve()
    if (
        directory not in candidate.parents
        or not candidate.is_file()
        or candidate.suffix.lower() != ".pdf"
    ):
        raise HTTPException(status_code=404, detail="pdf not found")
    return FileResponse(candidate, media_type="application/pdf")


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


@app.get("/api/runs")
def get_runs() -> dict:
    return {"runs": list_runs()}


@app.delete("/api/runs")
def clear_runs() -> dict:
    try:
        removed = clear_run_registry()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"removed": removed}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run_id = _safe_name(run_id)
    record = read_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record


@app.get("/api/runs/{run_id}/checkpoints")
def get_run_checkpoints(run_id: str) -> dict:
    run_id = _safe_name(run_id)
    if read_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"checkpoints": load_checkpoint_history(run_id)}


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str) -> StreamingResponse:
    run_id = _safe_name(run_id)
    record = read_run(run_id)
    replay, subscriber, closed = RUN_EVENTS.subscribe(run_id)
    if record is None and not replay:
        RUN_EVENTS.unsubscribe(run_id, subscriber)
        raise HTTPException(status_code=404, detail="run not found")

    def generate():
        events = list(replay)
        if closed and not events and record is not None:
            events = [
                {"type": "node", "run_id": run_id, "trace": trace}
                for trace in record.get("trace", [])
            ]
            events.append(
                {
                    "type": "run_end",
                    "run_id": run_id,
                    "status": record.get("status"),
                    "error": record.get("error"),
                    "finished_at": record.get("finished_at"),
                }
            )
        try:
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            while subscriber is not None:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            RUN_EVENTS.unsubscribe(run_id, subscriber)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


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
        return {
            "extracted_fields": {},
            "no_need_page": {},
            "multiple-docs": {"same-words-every-pages": {}},
        }
    return json.loads(config.TEMPLATE_PATH.read_text(encoding="utf-8"))


_process_state: dict = {
    "running": False,
    "last_exit_code": None,
    "error": None,
    "finished_at": None,
    "batch_started_ts": 0.0,
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
        _process_state["batch_started_ts"] = time.time()
    threading.Thread(target=_process_worker, daemon=True).start()
    return {"started": True}


@app.get("/api/process/status")
def process_status() -> dict:
    with _process_lock:
        state = dict(_process_state)
    batch_started_ts = state.get("batch_started_ts") or 0.0
    state["runs"] = [
        {
            "run_id": record.get("run_id", ""),
            "document": record.get("document", ""),
            "status": record.get("status", "running"),
            "started_at": record.get("started_at", ""),
        }
        for record in list_runs()
        if (record.get("started_ts") or 0.0) >= batch_started_ts
    ]
    return state


@app.put("/api/template")
def put_template(data: dict) -> dict:
    extracted = data.get("extracted_fields")
    no_need = data.get("no_need_page")
    multi_docs = data.get("multiple-docs") or {}
    same_words = (
        multi_docs.get("same-words-every-pages")
        if isinstance(multi_docs, dict)
        else None
    )
    if not isinstance(extracted, dict) or not isinstance(no_need, dict):
        raise HTTPException(
            status_code=422,
            detail="expected 'extracted_fields' and 'no_need_page' objects",
        )
    if isinstance(same_words, list):
        same_words = {str(name): "" for name in same_words}
    if not isinstance(same_words, dict):
        same_words = {}
    payload = {
        "extracted_fields": {
            str(key): "" for key in extracted if str(key).strip()
        },
        "no_need_page": {str(key): "" for key in no_need if str(key).strip()},
        "multiple-docs": {
            "same-words-every-pages": {
                str(key): "" for key in same_words if str(key).strip()
            }
        },
    }
    config.TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.TEMPLATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload
