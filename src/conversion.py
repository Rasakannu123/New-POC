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
    pages: list[Image.Image] = field(default_factory=list)
    page_count: int = 0
    success: bool = False
    error: str | None = None


class ImageConversionLayer:
    def __init__(self, dpi: int) -> None:
        self.dpi = dpi

    def convert_pages(self, pdf_path: Path | str) -> ConversionResult:
        pdf_path = Path(pdf_path)
        result = ConversionResult()
        try:
            pages = convert_from_path(str(pdf_path), dpi=self.dpi)
        except PDFInfoNotInstalledError:
            result.error = POPPLER_HELP
            logger.error("Poppler missing while converting %s", pdf_path.name)
        except (PDFPageCountError, PDFSyntaxError) as exc:
            result.error = f"Invalid or unreadable PDF: {exc}"
            logger.error("Failed converting %s: %s", pdf_path.name, exc)
        else:
            result.pages = pages
            result.page_count = len(pages)
            result.success = True
        return result
