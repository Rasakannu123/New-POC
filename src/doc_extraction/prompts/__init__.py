"""All LLM prompts, centralised in one folder."""

from src.doc_extraction.prompts.extraction import EXTRACTION_PROMPT, MAX_FIELDS
from src.doc_extraction.prompts.split import build_split_prompt

__all__ = [
    "EXTRACTION_PROMPT",
    "MAX_FIELDS",
    "build_split_prompt",
]
