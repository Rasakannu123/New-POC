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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


# --- Gateway connection ---------------------------------------------------
API_KEY = os.getenv("API_KEY", "")
BASE_URL = os.getenv("BASE_URL", "")

# --- Image-processing (vision) models -------------------------------------
MODEL_IMAGE_LARGE = os.getenv("IMAGE_MODEL_LARGE", "mistralai/mistral-large-2512")
MODEL_IMAGE_MEDIUM = os.getenv("IMAGE_MODEL_MEDIUM", "mistralai/mistral-medium-3.5")
MODEL_IMAGE_SMALL = os.getenv("IMAGE_MODEL_SMALL", "mistralai/mistral-small-2603")

# --- Model Router: quality tier -> extraction model -----------------------
TIER_MODEL_MAP = {
    "clear": os.getenv("TIER_CLEAR_MODEL", MODEL_IMAGE_SMALL),
    "blurry": os.getenv("TIER_BLURRY_MODEL", MODEL_IMAGE_MEDIUM),
    "very_blurry": os.getenv("TIER_VERY_BLURRY_MODEL", MODEL_IMAGE_LARGE),
}

# --- Pipeline settings -----------------------------------------------------
DPI = int(os.getenv("DPI", "300"))
IMAGE_FORMAT = os.getenv("IMAGE_FORMAT", "png")

# --- Asynchronous processing -----------------------------------------------
# Maximum number of documents processed at the same time; the remaining
# documents wait in a queue. All pages of a document run concurrently,
# bounded only by the per-feature limits below.
MAX_CONCURRENT_DOCUMENTS = int(os.getenv("MAX_CONCURRENT_DOCUMENTS", "4"))

# Per-feature page concurrency: how many pages of one document may be
# inside each page feature at the same time. Every document has its own
# limits, so documents run at the same time without sharing lanes. The
# converter is not here - it runs once per document, before pages start.
FEATURE_CONCURRENCY = {
    "enhance": int(os.getenv("IMAGE_ENHANCEMENT_CONCURRENCY", "5")),
    "assess": int(os.getenv("QUALITY_ASSESSMENT_CONCURRENCY", "3")),
    "route": int(os.getenv("MODEL_ROUTER_CONCURRENCY", "2")),
    "extract": int(os.getenv("DATA_EXTRACTION_CONCURRENCY", "4")),
}

# --- Latency thresholds per node (seconds) ---------------------------------
# A node slower than its threshold is reported as OVER-THRESHOLD in the
# terminal; it never fails the run.
LATENCY_THRESHOLDS = {
    "convert": float(os.getenv("LATENCY_THRESHOLD_CONVERT", "120")),
    "enhance": float(os.getenv("LATENCY_THRESHOLD_ENHANCE", "30")),
    "assess": float(os.getenv("LATENCY_THRESHOLD_ASSESS", "60")),
    "route": float(os.getenv("LATENCY_THRESHOLD_ROUTE", "5")),
    "extract": float(os.getenv("LATENCY_THRESHOLD_EXTRACT", "120")),
    "output": float(os.getenv("LATENCY_THRESHOLD_OUTPUT", "30")),
}

# --- LLM retry limits ------------------------------------------------------
# Retries per page after a failed API call, and the total retries allowed for
# one document. 0 means "never retry".
LLM_PAGE_RETRY_LIMIT = int(os.getenv("LLM_PAGE_RETRY_LIMIT", "2"))
LLM_DOCUMENT_RETRY_LIMIT = int(os.getenv("LLM_DOCUMENT_RETRY_LIMIT", "5"))

# --- Token limits ----------------------------------------------------------
# Cumulative model token budget (input + output) for one document; when it is
# reached, no further model calls are made for that document.
# 0 (or less) means unlimited.
DOCUMENT_TOKEN_LIMIT = int(os.getenv("DOCUMENT_TOKEN_LIMIT", "100000"))

INPUT_DIR = Path(os.getenv("INPUT_DIR") or PROJECT_ROOT / "data" / "input")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or PROJECT_ROOT / "data" / "output")

# --- Extraction template ----------------------------------------------------
# Optional JSON schema ("extracted_fields": {field: ...}) that locks the
# extraction to a fixed set of fields. Missing file -> free-form extraction.
TEMPLATE_PATH = Path(
    os.getenv("TEMPLATE_PATH") or PROJECT_ROOT / "data" / "Template" / "test.json"
)


def _load_template_fields(path: Path) -> list[str]:
    """Reads the field names from the template so extraction can be locked to
    exactly those fields; returns [] when the file is missing or broken so
    extraction falls back to free-form mode instead of crashing."""
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

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
