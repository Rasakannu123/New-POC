"""
Split Layer (Page Relevance Gate)
---------------------------------
Decides locally (no model call) whether a page is needed before spending
an extraction call. Active only when the template defines "no_need_page"
fields.

    page image -> Tesseract OCR text -> local keyword matching -> verdict

    matched (exact or fuzzy >= threshold) -> page not needed (skip folder)
    no match                              -> page needed (extraction)
    no OCR text                           -> Manual-Review folder

The verdict is fully deterministic. SPLIT_MODEL in config is reserved for
an optional future fallback on borderline pages (not used).
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from PIL import Image

from src.doc_extraction import config

logger = logging.getLogger(__name__)

VERDICT_YES = "yes"
VERDICT_NO = "no"
VERDICT_UNCLEAR = "unclear"

FUZZY_MATCH_THRESHOLD = 0.85
MAX_PAGE_TEXT_CHARS = 15000

_CONFUSABLES = str.maketrans({"-": " ", "_": " ", "0": "o", "1": "l"})


@dataclass
class SplitDecision:
    """Outcome of the page relevance check for one page."""

    verdict: str
    raw_reply: str = ""
    reason: str = ""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower()).translate(_CONFUSABLES)
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(text.split())


class SplitEngine:
    """Filters out not-needed pages before the extraction model runs."""

    def __init__(
        self,
        no_need_fields: list[str] | None = None,
        ocr_config: str = "--psm 3",
    ) -> None:
        self.no_need_fields = [str(field) for field in (no_need_fields or [])]
        self.enabled = bool(self.no_need_fields)
        self.ocr_config = ocr_config
        self._pytesseract = None
        self._ocr_semaphore = threading.Semaphore(config.OCR_CONCURRENCY)
        self._init_ocr()

    def classify(self, image: Image.Image) -> SplitDecision:
        if not self.enabled:
            return SplitDecision(VERDICT_NO, reason="no_need_page gate disabled")
        if self._pytesseract is None:
            logger.warning("Tesseract unavailable; page treated as needed.")
            return SplitDecision(VERDICT_NO, reason="tesseract unavailable")
        page_text = self._ocr_text(image)[:MAX_PAGE_TEXT_CHARS]
        if not page_text.strip():
            return SplitDecision(
                VERDICT_UNCLEAR, reason="page has no OCR text (unreadable)"
            )
        return self._match_keywords(page_text)

    def _ocr_text(self, image: Image.Image) -> str:
        with self._ocr_semaphore:
            return self._pytesseract.image_to_string(image, config=self.ocr_config)

    def _match_keywords(self, page_text: str) -> SplitDecision:
        text_norm = _normalize(page_text)
        words = text_norm.split()
        best_keyword = ""
        best_ratio = 0.0

        for keyword in self.no_need_fields:
            keyword_norm = _normalize(keyword)
            if not keyword_norm:
                continue
            if re.search(rf"\b{re.escape(keyword_norm)}\b", text_norm):
                best_keyword, best_ratio = keyword, 1.0
                break
            window = len(keyword_norm.split())
            if window == 0 or len(words) < window:
                continue
            for start in range(len(words) - window + 1):
                chunk = " ".join(words[start : start + window])
                ratio = SequenceMatcher(None, keyword_norm, chunk).ratio()
                if ratio > best_ratio:
                    best_keyword, best_ratio = keyword, ratio

        if best_ratio >= FUZZY_MATCH_THRESHOLD:
            return SplitDecision(
                VERDICT_YES,
                raw_reply=f"matched '{best_keyword}'",
                reason=(
                    f"no_need_page field '{best_keyword}' matched "
                    f"(similarity {best_ratio:.2f})"
                ),
            )
        return SplitDecision(VERDICT_NO, reason="no no_need_page field matched")

    def _init_ocr(self) -> None:
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract not installed - split gate disabled.")
            return

        if shutil.which("tesseract") is None:
            logger.warning(
                "Tesseract binary not found on PATH - split gate disabled."
            )
            return

        self._pytesseract = pytesseract
