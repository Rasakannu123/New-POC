"""
Central configuration, loaded entirely from the project .env file.

Every endpoint, key, model identifier and pipeline setting lives in .env
(see .env.example for the full list of keys). No secret is hard-coded here.
"""

from __future__ import annotations

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