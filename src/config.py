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
POPPLER_PATH = os.getenv("POPPLER_PATH") or None
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "4"))

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

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
