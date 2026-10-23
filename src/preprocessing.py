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
    4. Binarization         - Otsu threshold (opt-in, OFF by default)

Deskew (measure + rotate) and CLAHE contrast were removed for speed: the
scanned documents here are already straight and high-contrast, so those
steps cost time without improving the quality score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_BLUR_LAPLACIAN_THRESHOLD = 50.0


@dataclass
class PreprocessingReport:
    """Diagnostics describing what the engine did to one image."""

    steps_applied: list[str] = field(default_factory=list)
    pre_binarize_image: Image.Image | None = None


class ImagePreprocessingEngine:
    """Enhances document page images using classical OpenCV techniques."""

    def __init__(
        self,
        denoise: bool = True,
        deblur: bool = True,
        binarize: bool = False,
    ) -> None:
        """Every step is a switch so quality can be tuned per document type -
        for example binarize stays off because it can destroy grey photos."""
        self.denoise = denoise
        self.deblur = deblur
        self.binarize = binarize

    def enhance(self, image: Image.Image) -> Image.Image:
        """The image-only entry point used by the pipeline when the diagnostics
        report is not needed."""
        enhanced, _report = self.enhance_with_report(image)
        return enhanced

    def enhance_with_report(
        self, image: Image.Image
    ) -> tuple[Image.Image, PreprocessingReport]:
        """Runs the full cleanup chain and reports which steps were applied, so
        quality problems can be traced back to a specific step later."""
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

    @staticmethod
    def _wiener_deblur(
        gray: np.ndarray,
        psf_sigma: float = 2.0,
        noise_ratio: float = 0.02,
    ) -> np.ndarray:
        """Sharpens motion-blurred scans with frequency-domain deconvolution;
        only invoked on detected-blurry pages so sharp pages are never damaged."""
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
        """Boosts edge contrast after deblurring so characters regain crisp
        borders for OCR."""
        blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=sigma)
        return cv2.addWeighted(gray, 1.0 + amount, blurred, -amount, 0)
