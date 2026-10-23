import threading

from src import config

COUNTER_FILE = config.OUTPUT_DIR / ".document_id_counter"

_lock = threading.Lock()


def _read_counter() -> int:
    try:
        return int(COUNTER_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def allocate_document_id() -> str:
    with _lock:
        current = _read_counter() + 1
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        COUNTER_FILE.write_text(str(current), encoding="utf-8")
        return f"{current:04d}"


def page_id_for(document_id: str, page_number: int) -> str:
    return f"{document_id}/{page_number:02d}"
