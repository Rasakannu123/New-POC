import cv2
import numpy as np
from PIL import Image

_BLUR_LAPLACIAN_THRESHOLD = 50.0


class ImagePreprocessingEngine:
    def __init__(
        self,
        denoise: bool = True,
        deblur: bool = True,
        binarize: bool = False,
    ) -> None:
        self.denoise = denoise
        self.deblur = deblur
        self.binarize = binarize

    def enhance(self, image: Image.Image) -> Image.Image:
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)

        if self.deblur:
            if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < _BLUR_LAPLACIAN_THRESHOLD:
                gray = self._unsharp_mask(self._wiener_deblur(gray))

        if self.denoise:
            gray = cv2.medianBlur(gray, 3)

        if self.binarize and float(gray.std()) >= 5.0:
            gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        return Image.fromarray(gray)

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
