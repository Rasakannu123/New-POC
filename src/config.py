import json
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


API_KEY = os.environ["API_KEY"]
BASE_URL = os.environ["BASE_URL"]


TIER_MODEL_MAP = {
    "clear": os.environ["TIER_CLEAR_MODEL"],
    "blurry": os.environ["TIER_BLURRY_MODEL"],
    "very_blurry": os.environ["TIER_VERY_BLURRY_MODEL"],
}


DPI = 300
IMAGE_FORMAT = "png"


MAX_CONCURRENT_DOCUMENTS = int(os.environ["MAX_CONCURRENT_DOCUMENTS"])

FEATURE_CONCURRENCY = {
    "enhance": int(os.environ["IMAGE_ENHANCEMENT_CONCURRENCY"]),
    "assess": int(os.environ["QUALITY_ASSESSMENT_CONCURRENCY"]),
    "route": int(os.environ["MODEL_ROUTER_CONCURRENCY"]),
    "extract": int(os.environ["DATA_EXTRACTION_CONCURRENCY"]),
}

LATENCY_THRESHOLDS = {
    "convert": float(os.environ["LATENCY_THRESHOLD_CONVERT"]),
    "enhance": float(os.environ["LATENCY_THRESHOLD_ENHANCE"]),
    "assess": float(os.environ["LATENCY_THRESHOLD_ASSESS"]),
    "route": float(os.environ["LATENCY_THRESHOLD_ROUTE"]),
    "extract": float(os.environ["LATENCY_THRESHOLD_EXTRACT"]),
    "output": float(os.environ["LATENCY_THRESHOLD_OUTPUT"]),
}


LLM_PAGE_RETRY_LIMIT = int(os.environ["LLM_PAGE_RETRY_LIMIT"])
LLM_DOCUMENT_RETRY_LIMIT = int(os.environ["LLM_DOCUMENT_RETRY_LIMIT"])


DOCUMENT_TOKEN_LIMIT = int(os.environ["DOCUMENT_TOKEN_LIMIT"])


INPUT_DIR = Path(os.getenv("INPUT_DIR") or PROJECT_ROOT / "data" / "input")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR") or PROJECT_ROOT / "data" / "output")


TEMPLATE_PATH = Path(
    os.getenv("TEMPLATE_PATH") or PROJECT_ROOT / "data" / "Template" / "test.json"
)


def _load_template_fields(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    block = data.get("extracted_fields", data) if isinstance(data, dict) else data
    return [str(name) for name in block] if isinstance(block, (dict, list)) else []


TEMPLATE_FIELDS = _load_template_fields(TEMPLATE_PATH)

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
