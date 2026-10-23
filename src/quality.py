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
_OCR_MAX_SIDE = 1500


@dataclass
class QualityAssessment:
    score: float
    tier: str


class QualityAssessmentEngine:
    def __init__(
        self,
        clear_threshold: float = 80.0,
        blurry_threshold: float = 50.0,
        ocr_config: str = "--oem 1 --psm 6 -c tessedit_do_invert=0",
    ) -> None:
        self.clear_threshold = float(clear_threshold)
        self.blurry_threshold = float(blurry_threshold)
        self.ocr_config = ocr_config
        self._pytesseract = None
        self._init_ocr()

    def assess(self, image: Image.Image) -> QualityAssessment:
        if max(image.size) > _OCR_MAX_SIDE:
            scale = _OCR_MAX_SIDE / max(image.size)
            image = image.resize(
                (round(image.width * scale), round(image.height * scale))
            )
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
        if self._pytesseract is None:
            return 0.0

        try:
            data = self._pytesseract.image_to_data(
                gray,
                output_type=self._pytesseract.Output.DICT,
                config=self.ocr_config,
            )

            confidences: list[float] = []
            weights: list[int] = []

            for text, confidence in zip(data.get("text", []), data.get("conf", [])):
                text = str(text or "").strip()
                if not text:
                    continue
                try:
                    conf = float(confidence)
                except (TypeError, ValueError):
                    continue
                if conf < 0.0:
                    continue
                clipped = float(np.clip(conf, 0.0, 100.0))
                if clipped >= READABLE_MIN_CONFIDENCE:
                    confidences.append(clipped)
                    weights.append(len("".join(text.split())))

            if not confidences:
                return 0.0

            mean_confidence = float(np.average(confidences, weights=weights))
            return float(np.clip(mean_confidence, 0.0, 100.0))

        except Exception as exc:
            logger.warning("OCR-confidence metric failed: %s", exc)
            return 0.0

    def _init_ocr(self) -> None:
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract not installed - OCR confidence will be 0.")
            return

        if shutil.which("tesseract") is None:
            logger.warning("Tesseract binary not found on PATH - OCR confidence will be 0.")
            return

        self._pytesseract = pytesseract
        logger.info("OCR-confidence metric enabled (Tesseract found).")
