"""
Image Preprocessing Engine (Core Component #3)
----------------------------------------------
Improves image quality using OpenCV, positioned between the
Image Conversion Layer and the Quality Assessment Engine:

    PDF -> images -> [this engine] -> enhanced images -> Output

Pipeline (each step can be toggled individually):
    1. Grayscale conversion
    2. Deblurring           - Wiener deconvolution + unsharp mask
                              (adaptive: only applied when the page is blurry)
    3. Denoising            - median filter (edge-preserving, speckle removal)
    4. Deskewing            - Hough-transform angle estimation + rotation
                              (minAreaRect fallback when no lines are found)
    5. Contrast enhancement - CLAHE
    6. Binarization         - Otsu threshold (opt-in, OFF by default)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MIN_DESKEW_ANGLE_DEG = 0.3
_BLUR_LAPLACIAN_THRESHOLD = 50.0


@dataclass
class PreprocessingReport:
    """Diagnostics describing what the engine did to one image."""

    deskew_angle: float = 0.0
    steps_applied: list[str] = field(default_factory=list)
    pre_binarize_image: Image.Image | None = None


class ImagePreprocessingEngine:
    """Enhances document page images using classical OpenCV techniques."""

    def __init__(
        self,
        denoise: bool = True,
        deskew: bool = True,
        enhance_contrast: bool = True,
        deblur: bool = True,
        binarize: bool = False,
    ) -> None:
        self.denoise = denoise
        self.deskew = deskew
        self.enhance_contrast = enhance_contrast
        self.deblur = deblur
        self.binarize = binarize

    def enhance(self, image: Image.Image) -> Image.Image:
        enhanced, _report = self.enhance_with_report(image)
        return enhanced

    def enhance_with_report(
        self, image: Image.Image
    ) -> tuple[Image.Image, PreprocessingReport]:
        report = PreprocessingReport()

        rgb = np.array(image.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        report.steps_applied.append("grayscale")

        if self.deblur:
            if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < _BLUR_LAPLACIAN_THRESHOLD:
                gray = self._wiener_deblur(gray)
                gray = self._unsharp_mask(gray)
                report.steps_applied.append("deblur(wiener+unsharp)")
            else:
                report.steps_applied.append("deblur(skipped: already sharp)")

        if self.denoise:
            gray = cv2.medianBlur(gray, 3)
            report.steps_applied.append("denoise(median)")

        if self.deskew:
            angle = self._estimate_skew_angle(gray)
            report.deskew_angle = angle
            if abs(angle) >= MIN_DESKEW_ANGLE_DEG:
                gray = self._rotate(gray, angle)
                report.steps_applied.append(f"deskew({angle:+.2f}deg)")
                logger.info("Deskew applied: %+.2f deg", angle)
            else:
                report.steps_applied.append("deskew(skipped: already straight)")

        if self.enhance_contrast:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            report.steps_applied.append("contrast(CLAHE)")

        report.pre_binarize_image = Image.fromarray(gray.copy())

        if self.binarize:
            if float(gray.std()) < 5.0:
                report.steps_applied.append("binarize(skipped: blank page)")
            else:
                gray = cv2.threshold(
                    gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
                )[1]
                report.steps_applied.append("binarize(otsu)")

        return Image.fromarray(gray), report

    def _estimate_skew_angle(self, gray: np.ndarray) -> float:
        ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

        edges = cv2.Canny(ink, 50, 150, apertureSize=3)
        min_line_length = max(50, gray.shape[1] // 20)
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=80,
            minLineLength=min_line_length,
            maxLineGap=30,
        )

        if lines is not None and len(lines) > 0:
            angles = []
            for x1, y1, x2, y2 in lines[:, 0]:
                angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
                if abs(angle) <= 45:
                    angles.append(angle)
            if angles:
                return float(np.median(angles))

        ys, xs = np.where(ink > 0)
        if len(xs) == 0:
            return 0.0
        coords = np.column_stack([xs, ys])
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        return float(angle)

    @staticmethod
    def _rotate(gray: np.ndarray, angle: float) -> np.ndarray:
        height, width = gray.shape[:2]
        matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
        return cv2.warpAffine(
            gray,
            matrix,
            (width, height),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=255,
        )

    @staticmethod
    def _wiener_deblur(
        gray: np.ndarray,
        psf_sigma: float = 2.0,
        noise_ratio: float = 0.02,
    ) -> np.ndarray:
        height, width = gray.shape
        image = gray.astype(np.float32)

        kernel_size = max(3, int(psf_sigma * 6) | 1)
        axis = np.arange(kernel_size) - kernel_size // 2
        xx, yy = np.meshgrid(axis, axis)
        psf = np.exp(-(xx ** 2 + yy ** 2) / (2 * psf_sigma ** 2))
        psf /= psf.sum()

        psf_big = np.zeros((height, width), np.float32)
        psf_big[:kernel_size, :kernel_size] = psf
        psf_big = np.roll(np.roll(psf_big, -kernel_size // 2, 0), -kernel_size // 2, 1)

        otf = np.fft.fft2(psf_big)
        wiener = np.conj(otf) / (np.abs(otf) ** 2 + noise_ratio)

        deblurred = np.fft.ifft2(np.fft.fft2(image) * wiener).real
        return np.clip(deblurred, 0, 255).astype(np.uint8)

    @staticmethod
    def _unsharp_mask(gray: np.ndarray, amount: float = 1.0, sigma: float = 2.0) -> np.ndarray:
        blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma)
        return cv2.addWeighted(gray, 1.0 + amount, blurred, -amount, 0)