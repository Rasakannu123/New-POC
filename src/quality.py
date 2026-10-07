"""
Quality Assessment Engine (Core Component #4)
---------------------------------------------
Calculates a 0-100 quality score for each enhanced page image.

    1. Content        -> Tesseract per-word OCR confidence
    2. Readable words -> confidence >= 30 (stamps, borders, handwriting dropped)
    3. Quality Score  -> char-weighted mean of readable words
                         x coverage factor (readable chars / 120)
    4. Tier           -> clear / blurry / very_blurry

Tier thresholds:
    > 80   -> clear
    50-80  -> blurry
    < 50   -> very_blurry

Thread safety: how many pages are assessed in parallel is controlled at the
pipeline level by QUALITY_ASSESSMENT_CONCURRENCY; each assessment is an
independent Tesseract subprocess.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

TIER_CLEAR = "clear"
TIER_BLURRY = "blurry"
TIER_VERY_BLURRY = "very_blurry"

READABLE_MIN_CONFIDENCE = 30.0
COVERAGE_TARGET_CHARS = 120.0


@dataclass
class QualityAssessment:
    """Quality result for a single page image."""

    score: float
    tier: str


class QualityAssessmentEngine:
    """Scores page-image quality using Tesseract OCR confidence only."""

    def __init__(
        self,
        clear_threshold: float = 80.0,
        blurry_threshold: float = 50.0,
        ocr_config: str = "--psm 3",
    ) -> None:
        """Loads Tesseract once; the pipeline's QUALITY_ASSESSMENT_CONCURRENCY
        limit decides how many pages are scored at the same time."""
        self.clear_threshold = float(clear_threshold)
        self.blurry_threshold = float(blurry_threshold)
        self.ocr_config = ocr_config

        self._pytesseract = None
        self._init_ocr()

    def assess(self, image: Image.Image) -> QualityAssessment:
        """Produces the 0-100 score and quality tier - the decision input for
        the model router, so pages that need an expensive model can be told
        apart from pages that do not."""
        gray = np.array(image.convert("L"))
        score = round(self._ocr_confidence_score(gray), 1)

        if score > self.clear_threshold:
            tier = TIER_CLEAR
        elif score >= self.blurry_threshold:
            tier = TIER_BLURRY
        else:
            tier = TIER_VERY_BLURRY

        return QualityAssessment(score=score, tier=tier)

    def _ocr_confidence_score(self, gray: np.ndarray) -> float:
        """Measures how confidently Tesseract reads the page. Junk words below
        the confidence floor (stamps, borders, handwriting) are excluded so they
        cannot inflate the score, and the result is weighted by readable text
        coverage so a nearly empty page never scores high."""
        if self._pytesseract is None:
            return 0.0

        try:
            data = self._pytesseract.image_to_data(
                gray,
                output_type=self._pytesseract.Output.DICT,
                config=self.ocr_config,
            )

            all_confidences: list[float] = []
            all_char_weights: list[int] = []
            readable_confidences: list[float] = []
            readable_char_weights: list[int] = []

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
                clipped = float(np.clip(conf, 0.0, 100.0))
                all_confidences.append(clipped)
                all_char_weights.append(char_count)
                if clipped >= READABLE_MIN_CONFIDENCE:
                    readable_confidences.append(clipped)
                    readable_char_weights.append(char_count)

            if not readable_confidences or not readable_char_weights:
                return 0.0

            mean_confidence = float(
                np.average(readable_confidences, weights=readable_char_weights)
            )
            coverage = min(1.0, sum(readable_char_weights) / COVERAGE_TARGET_CHARS)
            score = mean_confidence * coverage

            return float(np.clip(score, 0.0, 100.0))

        except Exception as exc:
            logger.warning("OCR-confidence metric failed: %s", exc)
            return 0.0

    def _init_ocr(self) -> None:
        """Turns OCR on when Tesseract is installed and degrades gracefully to
        score 0 when it is not, so the pipeline still runs without OCR."""
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
