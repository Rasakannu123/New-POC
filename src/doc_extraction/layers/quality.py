"""
Quality Assessment Engine (Core Component #4)
---------------------------------------------
Calculates a 0-100 quality score for each enhanced page image.

    1. Content        -> Tesseract OCR overall page confidence
    2. Quality Score  -> OCR confidence only (Focus removed)
    3. Tier           -> clear / blurry / very_blurry

Tier thresholds:
    > 80   -> clear
    50-80  -> blurry
    < 50   -> very_blurry

Thread safety: pytesseract calls run in parallel up to config.OCR_CONCURRENCY,
guarded by an instance semaphore; each call is an independent Tesseract
subprocess.
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from src.doc_extraction import config

logger = logging.getLogger(__name__)

TIER_CLEAR = "clear"
TIER_BLURRY = "blurry"
TIER_VERY_BLURRY = "very_blurry"


@dataclass
class QualityAssessment:
    """Quality result for a single page image."""

    score: float
    tier: str
    metrics: dict[str, float] = field(default_factory=dict)


class QualityAssessmentEngine:
    """Scores page-image quality using Tesseract OCR confidence only."""

    def __init__(
        self,
        clear_threshold: float = 80.0,
        blurry_threshold: float = 50.0,
        ocr_config: str = "--psm 3",
    ) -> None:
        self.clear_threshold = float(clear_threshold)
        self.blurry_threshold = float(blurry_threshold)
        self.ocr_config = ocr_config

        self._pytesseract = None
        self._ocr_semaphore = threading.Semaphore(config.OCR_CONCURRENCY)
        self._init_ocr()

    def assess(self, image: Image.Image) -> QualityAssessment:
        gray = np.array(image.convert("L"))

        ocr_result = self._ocr_confidence_score(gray)

        metric_scores: dict[str, float] = {
            "ocr_confidence": ocr_result["score"],
            "ocr_word_count": ocr_result["word_count"],
            "ocr_char_count": ocr_result["char_count"],
            "ocr_mean_confidence": ocr_result["mean_confidence"],
        }

        score = round(float(np.clip(ocr_result["score"], 0.0, 100.0)), 1)

        if score > self.clear_threshold:
            tier = TIER_CLEAR
        elif score >= self.blurry_threshold:
            tier = TIER_BLURRY
        else:
            tier = TIER_VERY_BLURRY

        return QualityAssessment(
            score=score,
            tier=tier,
            metrics={
                name: round(float(value), 1)
                for name, value in metric_scores.items()
            },
        )

    def _ocr_confidence_score(self, gray: np.ndarray) -> dict[str, float]:
        if self._pytesseract is None:
            return {
                "score": 0.0,
                "mean_confidence": 0.0,
                "word_count": 0.0,
                "char_count": 0.0,
            }

        try:
            with self._ocr_semaphore:
                data = self._pytesseract.image_to_data(
                    gray,
                    output_type=self._pytesseract.Output.DICT,
                    config=self.ocr_config,
                )

            confidences: list[float] = []
            char_weights: list[int] = []

            for text, confidence in zip(
                data.get("text", []),
                data.get("conf", []),
            ):
                text = str(text or "").strip()
                if not text:
                    continue
                try:
                    conf = float(confidence)
                except (TypeError, ValueError):
                    continue
                if conf < 0.0:
                    continue
                char_count = len("".join(text.split()))
                if char_count <= 0:
                    continue
                confidences.append(float(np.clip(conf, 0.0, 100.0)))
                char_weights.append(char_count)

            word_count = len(confidences)
            total_chars = sum(char_weights)

            if word_count == 0 or total_chars == 0:
                return {
                    "score": 0.0,
                    "mean_confidence": 0.0,
                    "word_count": float(word_count),
                    "char_count": float(total_chars),
                }

            mean_confidence = float(
                np.average(confidences, weights=char_weights)
            )
            page_confidence = mean_confidence

            if word_count == 1:
                page_confidence *= 1.0 / 3.0
            elif word_count == 2:
                page_confidence *= 2.0 / 3.0

            return {
                "score": float(np.clip(page_confidence, 0.0, 100.0)),
                "mean_confidence": float(np.clip(mean_confidence, 0.0, 100.0)),
                "word_count": float(word_count),
                "char_count": float(total_chars),
            }

        except Exception as exc:
            logger.warning("OCR-confidence metric failed: %s", exc)
            return {
                "score": 0.0,
                "mean_confidence": 0.0,
                "word_count": 0.0,
                "char_count": 0.0,
            }

    def _init_ocr(self) -> None:
        try:
            import pytesseract
        except ImportError:
            logger.warning(
                "pytesseract not installed - OCR confidence will be 0."
            )
            return

        if shutil.which("tesseract") is None:
            logger.warning(
                "Tesseract binary not found on PATH - OCR confidence will be 0."
            )
            return

        self._pytesseract = pytesseract
        logger.info("OCR-confidence metric enabled (Tesseract found).")