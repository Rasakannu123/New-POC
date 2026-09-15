"""
Extraction prompt
-----------------
Sent with every page image to the model selected by the Model Router.
Asks for the top important fields as strict JSON with per-field confidence.

Deliberately strict about grounding: the model must transcribe only what
is legible in the image and skip anything uncertain, so unreadable pages
yield {} instead of hallucinated fields.
"""

MAX_FIELDS = 10

EXTRACTION_PROMPT = (
    "You are a document data-extraction engine. Examine this document page "
    "image and extract ONLY the top most important fields and their values "
    f"(at most {MAX_FIELDS} fields - e.g. document type, dates, names, "
    "amounts, reference numbers, addresses). "
    'Return ONLY a valid JSON object with this exact format: '
    '{"field_name": {"value": "extracted_value", "confidence": 85}}. '
    "STRICT GROUNDING RULES (highest priority): "
    "1. Extract only text you can clearly see and read in the image. "
    "2. Copy every value exactly and completely as printed - do NOT guess, "
    "infer, auto-complete, translate, or correct spelling from prior "
    "knowledge. "
    "3. Never return partial or truncated values: no '...', no '...', no "
    "incomplete words or cut-off numbers. If you can read only part of a "
    "value, SKIP that field entirely. "
    "4. If the page is very blurry or low quality, or you can only make "
    "out fragments of text, do NOT try to reconstruct the document from "
    "its layout, language, or document type - return exactly: {}. "
    "5. If a field is unreadable, unclear, or you are not certain its "
    "value is really printed on the page, SKIP that field entirely - "
    "never output empty values, placeholders like 'N/A' or 'unknown', "
    "or your best guess. "
    "6. Set confidence honestly: high (80-100) only when the text is "
    "fully legible, low (0-30) when it is partially legible or blurry. "
    "7. Never invent dates, amounts, names, or reference numbers, and "
    "never format or recompute values that are not printed as such. "
    "8. If no field can be read completely and with certainty, or the "
    "page contains no meaningful fields, return exactly: {}. "
    "No markdown, no code fences, no explanations."
)
