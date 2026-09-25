"""
Image Conversion Layer (Core Component #2)
------------------------------------------
Converts PDF documents into per-page, in-memory PIL images.

The pipeline orchestrator then runs, per page:
    Image Preprocessing Engine -> Quality Assessment Engine -> store.

Notes:
- Poppler location is resolved from the POPPLER_PATH environment
  variable when set, otherwise Poppler must be on the system PATH.
"""

from __future__ import annotations

import logging
import os
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
    "Poppler was not found. Install Poppler for Windows and either add its "
    "'bin' folder to the system PATH or set the POPPLER_PATH environment "
    "variable to that folder (e.g. C:\\poppler-26.02.0\\Library\\bin)."
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

    def __init__(self, dpi: int = 300, poppler_path: str | None = None) -> None:
        """Keeps the render DPI and the optional Poppler location, so callers
        can override them without touching environment variables."""
        self.dpi = dpi
        self.poppler_path = poppler_path or os.getenv("POPPLER_PATH")

    def convert_pages(self, pdf_path: Path | str) -> ConversionResult:
        """Renders every page of the PDF to an image - the first feature of the
        pipeline, because every later step works on page images. Failures are
        returned as result.error instead of raising, so one broken PDF can
        never crash the rest of the run."""
        pdf_path = Path(pdf_path)
        result = ConversionResult(source_pdf=pdf_path)

        try:
            pages = convert_from_path(
                str(pdf_path),
                dpi=self.dpi,
                poppler_path=self.poppler_path,
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
