"""
Split prompt (page relevance gate)
----------------------------------
Sent to the split model (config.SPLIT_MODEL) together with the Tesseract
OCR text of one page. The model must answer with a single word: "yes"
(the page matches a no_need_page field and is skipped) or "no" (the page
is needed and continues to extraction). Anything else counts as unclear
and sends the page to the Manual-Review folder.
"""

from __future__ import annotations


def build_split_prompt(no_need_fields: list[str], page_text: str) -> str:
    field_list = "\n".join(f'- "{field}"' for field in no_need_fields)
    return (
        "You are a document page classifier for a document-extraction pipeline.\n"
        "You receive the OCR text content of one document page.\n\n"
        "The page is NOT needed if it contains any of these fields or labels:\n"
        f"{field_list}\n\n"
        "Decide whether this page contains any of the listed fields or labels.\n"
        "Ignore case, spacing versus hyphens, and small OCR errors, but the "
        "field must genuinely appear in the page content - do not guess from "
        "the document type or layout alone.\n\n"
        "Answer rules:\n"
        '- Reply with exactly one word: "yes" or "no".\n'
        '- "yes" = the page is NOT needed (a listed field appears in the content).\n'
        '- "no" = the page IS needed (no listed field appears in the content).\n'
        "No explanations, no punctuation, no other text.\n\n"
        "PAGE CONTENT:\n"
        f"{page_text}"
    )
