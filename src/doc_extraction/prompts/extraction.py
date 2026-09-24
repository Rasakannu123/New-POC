"""
Extraction prompt
-----------------
Sent with every page image to the model selected by the Model Router.

If a field template is configured (config.TEMPLATE_FIELDS, loaded from
TEMPLATE_PATH), extraction is locked to exactly those fields and every
missing or unreadable field is returned as null. Without a template the
model extracts the top important fields free-form.

Deliberately strict about grounding: the model must transcribe only what
is legible in the image and never reconstruct values it cannot read.
"""

from __future__ import annotations

from src.doc_extraction import config

MAX_FIELDS = 10

_GROUNDING_RULES = (
    "STRICT GROUNDING RULES (highest priority): "
    "1. Extract only text you can clearly see and read in the image. "
    "2. Copy every value exactly and completely as printed - do NOT guess, "
    "infer, auto-complete, translate, or correct spelling from prior "
    "knowledge. "
    "3. Never return partial or truncated values: no '...', no incomplete "
    "words or cut-off numbers. If you can read only part of a value, "
    "treat the field as unreadable. "
    "4. If the page is very blurry or low quality, or you can only make "
    "out fragments of text, do NOT try to reconstruct the document from "
    "its layout, language, or document type. "
    "5. Never invent dates, amounts, names, or reference numbers, and "
    "never format or recompute values that are not printed as such. "
    "6. Set confidence honestly: high (80-100) only when the text is "
    "fully legible, low (0-30) when it is partially legible or blurry. "
)


def build_extraction_prompt(
    template_fields: list[str] | None = None,
    helper_fields: list[str] | None = None,
) -> str:
    """Build the extraction prompt, optionally locked to template fields."""
    if template_fields:
        field_list = ", ".join(f'"{name}"' for name in template_fields)
        scope = (
            "Extract EXACTLY these fields and no others: "
            f"{field_list}. "
            "Return one entry for every listed field, in the same order. "
            "If a field does not appear on the page, or its value cannot "
            'be read completely, set its "value" to null and its '
            '"confidence" to 0 - never omit the field and never guess '
            "its value. "
        )
        fallback_rule = ""
    else:
        scope = (
            "Extract ONLY the top most important fields and their values "
            f"(at most {MAX_FIELDS} fields - e.g. document type, dates, "
            "names, amounts, reference numbers, addresses). "
        )
        fallback_rule = (
            "7. If a field is unreadable, unclear, or you are not certain "
            "its value is really printed on the page, SKIP that field "
            "entirely - never output empty values, placeholders like "
            "'N/A' or 'unknown', or your best guess. "
            "8. If no field can be read completely and with certainty, or "
            "the page contains no meaningful fields, return exactly: {}. "
        )

    helper_rule = ""
    extra_helpers = [
        name for name in (helper_fields or []) if name not in (template_fields or [])
    ]
    if extra_helpers:
        helper_list = ", ".join(f'"{name}"' for name in extra_helpers)
        helper_rule = (
            "ADDITIONALLY, for internal document grouping, extract these "
            f"helper fields in the same JSON object, same format: "
            f"{helper_list}. "
            "Copy each helper value exactly as printed on the page; if it "
            'is not visible, set its "value" to null. '
        )

    return (
        "You are a document data-extraction engine. Examine this document "
        "page image. "
        + scope
        + helper_rule
        + 'Return ONLY a valid JSON object with this exact format: '
        '{"field_name": {"value": "extracted_value", "confidence": 85}}. '
        + _GROUNDING_RULES
        + fallback_rule
        + "No markdown, no code fences, no explanations."
    )


EXTRACTION_PROMPT = build_extraction_prompt(
    config.TEMPLATE_FIELDS,
    config.MULTI_DOC_FIELDS,
)
