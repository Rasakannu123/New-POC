"""
Document and page identity
--------------------------
Every document gets a unique document ID ("0001") and every page gets a page
ID built from the document ID and the page number ("0001/01").

Processing, routing and logging identify documents and pages by these IDs,
never by file name - file names can repeat or change, IDs cannot.

The ID counter is persisted in data/output/.document_id_counter so IDs stay
unique across runs.
"""

from __future__ import annotations

import threading

from src import config

COUNTER_FILE = config.OUTPUT_DIR / ".document_id_counter"

_lock = threading.Lock()


def _read_counter() -> int:
    """Reads the last allocated number; a missing or broken counter file just
    restarts the sequence instead of failing the run."""
    try:
        return int(COUNTER_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def allocate_document_id() -> str:
    """Returns the next unique document ID and persists the counter, so two
    runs can never hand out the same document ID."""
    with _lock:
        current = _read_counter() + 1
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        COUNTER_FILE.write_text(str(current), encoding="utf-8")
        return f"{current:04d}"


def page_id_for(document_id: str, page_number: int) -> str:
    """Builds the page ID from the document ID and the 1-based page number:
    document "0001", page 2 -> "0001/02"."""
    return f"{document_id}/{page_number:02d}"
