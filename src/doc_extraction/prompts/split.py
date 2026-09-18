"""
Split prompt (page relevance gate) - RESERVED FOR FUTURE USE
-------------------------------------------------------------
The split gate currently matches no_need_page keywords locally
(layers/split.py) and does not call a model. This prompt is kept for an
optional future fallback: sending only borderline pages to the model
(config.SPLIT_MODEL) for a yes/no second opinion.
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
