"""
Split Layer (Page Relevance Gate)
---------------------------------
Decides whether a page is needed at all before spending an extraction
call. Active only when the template defines "no_need_page" fields.

    page image -> Tesseract OCR text -> split model -> yes / no

    yes      -> page not needed (skipped)
    no       -> page needed (continue to quality/routing/extraction)
    unclear  -> page goes to the Manual-Review folder
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
from dataclasses import dataclass

from PIL import Image

from src.doc_extraction import config
from src.doc_extraction.layers.router import ModelRouter
from src.doc_extraction.prompts.split import build_split_prompt

logger = logging.getLogger(__name__)

VERDICT_YES = "yes"
VERDICT_NO = "no"
VERDICT_UNCLEAR = "unclear"

MAX_PAGE_TEXT_CHARS = 15000

_WORD_REPLY = re.compile(r"\b(yes|no)\b")


@dataclass
class SplitDecision:
    """Outcome of the page relevance check for one page."""

    verdict: str
    raw_reply: str = ""
    reason: str = ""


class SplitEngine:
    """Filters out not-needed pages before the extraction model runs."""

    def __init__(
        self,
        no_need_fields: list[str] | None = None,
        client=None,
        ocr_config: str = "--psm 3",
    ) -> None:
        self.no_need_fields = [str(field) for field in (no_need_fields or [])]
        self.enabled = bool(self.no_need_fields)
        self._client = client
        self.ocr_config = ocr_config
        self._pytesseract = None
        self._ocr_lock = threading.Lock()
        self._init_ocr()

    def classify(self, image: Image.Image) -> SplitDecision:
        if not self.enabled:
            return SplitDecision(VERDICT_NO, reason="no_need_page gate disabled")
        if self._pytesseract is None:
            logger.warning("Tesseract unavailable; page treated as needed.")
            return SplitDecision(VERDICT_NO, reason="tesseract unavailable")
        page_text = self._ocr_text(image)
        if not page_text.strip():
            return SplitDecision(
                VERDICT_UNCLEAR, reason="page has no OCR text (unreadable)"
            )
        raw_reply = self._ask_model(page_text)
        verdict = self._parse_verdict(raw_reply)
        return SplitDecision(verdict=verdict, raw_reply=raw_reply)

    def _ocr_text(self, image: Image.Image) -> str:
        with self._ocr_lock:
            return self._pytesseract.image_to_string(image, config=self.ocr_config)

    def _ask_model(self, page_text: str) -> str:
        try:
            response = self._get_client().chat.completions.create(
                model=config.SPLIT_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": build_split_prompt(
                            self.no_need_fields,
                            page_text[:MAX_PAGE_TEXT_CHARS],
                        ),
                    }
                ],
                max_tokens=200,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.error("Split check failed: %s", exc)
            return ""

    @staticmethod
    def _parse_verdict(raw: str) -> str:
        matches = _WORD_REPLY.findall((raw or "").lower())
        if not matches:
            return VERDICT_UNCLEAR
        return VERDICT_YES if matches[-1] == "yes" else VERDICT_NO

    def _get_client(self):
        if self._client is None:
            self._client = ModelRouter.create_client()
        return self._client

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
