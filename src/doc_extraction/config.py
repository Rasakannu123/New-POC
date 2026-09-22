"""
Central configuration, loaded entirely from the project .env file.

Every endpoint, key, model identifier and pipeline setting lives in .env
(see .env.example for the full list of keys). No secret is hard-coded here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# --- Gateway connection ---------------------------------------------------
API_KEY = os.getenv("API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "")

# --- Image-processing (vision) models -------------------------------------
MODEL_IMAGE_LARGE = os.getenv("IMAGE_MODEL_LARGE", "mistralai/mistral-large-2512")
MODEL_IMAGE_MEDIUM = os.getenv("IMAGE_MODEL_MEDIUM", "mistralai/mistral-medium-3.5")
MODEL_IMAGE_SMALL = os.getenv("IMAGE_MODEL_SMALL", "mistralai/mistral-small-2603")
MODEL_IMAGE_MINI = os.getenv("IMAGE_MODEL_MINI", "mistralai/ministral-14b")

# --- Model Router: quality tier -> extraction model -----------------------
# Inexpensive models handle good-quality pages; stronger models are reserved
# for hard cases.
TIER_MODEL_MAP = {
    "clear": os.getenv("TIER_CLEAR_MODEL", MODEL_IMAGE_SMALL),
    "blurry": os.getenv("TIER_BLURRY_MODEL", MODEL_IMAGE_MEDIUM),
    "very_blurry": os.getenv("TIER_VERY_BLURRY_MODEL", MODEL_IMAGE_LARGE),
}

# --- Pipeline settings -----------------------------------------------------
DPI = _int("DPI", 300)
IMAGE_FORMAT = os.getenv("IMAGE_FORMAT", "png")
POPPLER_PATH = os.getenv("POPPLER_PATH") or None

INPUT_DIR = Path(os.getenv("INPUT_DIR") or PROJECT_ROOT / "data" / "input")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or PROJECT_ROOT / "data" / "output")

# --- Extraction template ----------------------------------------------------
# Optional JSON schema ("extracted_fields": {field: ...}) that locks the
# extraction to a fixed set of fields. Missing file -> free-form extraction.
TEMPLATE_PATH = Path(
    os.getenv("TEMPLATE_PATH") or PROJECT_ROOT / "data" / "Template" / "test.json"
)


def _load_template_fields(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    block = data.get("extracted_fields", data) if isinstance(data, dict) else data
    if isinstance(block, dict):
        return [str(name) for name in block]
    if isinstance(block, list):
        return [str(name) for name in block]
    return []


TEMPLATE_FIELDS = _load_template_fields(TEMPLATE_PATH)


def _load_no_need_page_fields(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    block = data.get("no_need_page") or {}
    if isinstance(block, dict):
        return [str(name) for name in block]
    if isinstance(block, list):
        return [str(name) for name in block]
    return []


NO_NEED_PAGE_FIELDS = _load_no_need_page_fields(TEMPLATE_PATH)


def _load_multi_doc_fields(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    block = data.get("multiple-docs") or {}
    fields = block.get("same-words-every-pages") if isinstance(block, dict) else None
    if isinstance(fields, dict):
        return [str(name) for name in fields]
    if isinstance(fields, list):
        return [str(name) for name in fields]
    return []


MULTI_DOC_FIELDS = _load_multi_doc_fields(TEMPLATE_PATH)

# --- Split gate (page relevance) --------------------------------------------
# The gate matches no_need_page keywords locally (no model call).
# Reserved for an optional future model fallback on borderline pages.
SPLIT_MODEL = os.getenv("SPLIT_MODEL", "qwen/qwen-plus-2025-07-28:free")
# Pages with an unclear split verdict are parked here for manual review.
MANUAL_REVIEW_DIR = Path(
    os.getenv("MANUAL_REVIEW_DIR") or PROJECT_ROOT / "data" / "Manual-Review"
)
# Pages the split gate marked as not needed are stored here.
SKIP_DIR = Path(os.getenv("SKIP_DIR") or PROJECT_ROOT / "data" / "skip")

# --- Concurrency -----------------------------------------------------------
# Documents processed in parallel (thread pool; Poppler releases the GIL).
MAX_CONCURRENT_DOCUMENTS = _int("MAX_CONCURRENT_DOCUMENTS", 2)
# Pages extracted in parallel (async tasks capped by this semaphore).
MAX_CONCURRENT_PAGES = _int("MAX_CONCURRENT_PAGES", 4)
# Worker processes for the CPU-bound preprocessing stage (0 = cpu_count).
PREPROCESS_WORKERS = _int("PREPROCESS_WORKERS", 0) or (os.cpu_count() or 1)
# Worker threads for the Tesseract subprocess calls in quality assessment.
ASSESS_WORKERS = _int("ASSESS_WORKERS", 4)
# Concurrent Tesseract processes allowed per OCR consumer (quality + split).
OCR_CONCURRENCY = _int("OCR_CONCURRENCY", 4)

os.environ.setdefault("OMP_THREAD_LIMIT", "1")