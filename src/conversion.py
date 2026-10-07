"""
Image Conversion Layer (Core Component #2)
------------------------------------------
Converts a whole PDF document into per-page, in-memory PIL images in one
render call. The converter works at document level only - once the document
is converted into pages, every page is processed through the remaining
features (enhance, assess, route, extract) and never converted again.

Notes:
- Poppler must be installed and available on the system PATH.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pdf2image import convert_from_path
from pdf2image.exceptions import (
    PDFInfoNotInstalledError,
    PDFPageCountError,
    PDFSyntaxError,
)
from PIL import Image

logger = logging.getLogger(__name__)

POPPLER_HELP = (
    "Poppler was not found. Install Poppler for Windows and add its "
    "'bin' folder to the system PATH "
    "(e.g. C:\\poppler-26.02.0\\Library\\bin)."
)


@dataclass
class ConversionResult:
    """Outcome of converting a single PDF document."""

    source_pdf: Path
    pages: list[Image.Image] = field(default_factory=list)
    page_count: int = 0
    success: bool = False
    error: str | None = None


class ImageConversionLayer:
    """Converts each page of a PDF into an in-memory image."""

    def __init__(self, dpi: int = 300) -> None:
        """Keeps the render DPI, so callers can override it without touching
        environment variables."""
        self.dpi = dpi

    def convert_pages(self, pdf_path: Path | str) -> ConversionResult:
        """Renders every page of the PDF to an image in one call - the first
        feature of the pipeline, because every later step works on page
        images. Failures are returned as result.error instead of raising, so
        one broken PDF can never crash the rest of the run."""
        pdf_path = Path(pdf_path)
        result = ConversionResult(source_pdf=pdf_path)

        try:
            pages = convert_from_path(
                str(pdf_path),
                dpi=self.dpi,
            )
        except PDFInfoNotInstalledError:
            result.error = POPPLER_HELP
            logger.error("Poppler missing while converting %s", pdf_path.name)
            return result
        except (PDFPageCountError, PDFSyntaxError) as exc:
            result.error = f"Invalid or unreadable PDF: {exc}"
            logger.error("Failed converting %s: %s", pdf_path.name, exc)
            return result

        result.pages = pages
        result.page_count = len(pages)
        result.success = True
        return result
