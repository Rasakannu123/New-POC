"""
Extraction Layer
----------------
Sends each enhanced page image to the model selected by the Model Router
and extracts fields and values as structured JSON.

    Enhanced image + RoutingDecision -> gateway vision model -> fields

- Extraction is locked to the configured template fields when
  config.TEMPLATE_FIELDS is set; missing fields are returned as null.
  Otherwise the top important fields are requested (max 10).
- Images are downscaled to max 2048 px on the long side before sending.
- Responses are parsed robustly (code fences stripped, first JSON object
  extracted). A failed page never stops the pipeline.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from dataclasses import dataclass, field

from PIL import Image

from src import config
from src.router import ModelRouter, RoutingDecision

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 2048
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


def build_extraction_prompt(template_fields: list[str] | None = None) -> str:
    """Build the extraction prompt, optionally locked to template fields.

    The grounding rules exist because vision models happily invent plausible
    values - the prompt forces them to transcribe only what is legible."""
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

    return (
        "You are a document data-extraction engine. Examine this document "
        "page image. "
        + scope
        + 'Return ONLY a valid JSON object with this exact format: '
        '{"field_name": {"value": "extracted_value", "confidence": 85}}. '
        + _GROUNDING_RULES
        + fallback_rule
        + "No markdown, no code fences, no explanations."
    )


EXTRACTION_PROMPT = build_extraction_prompt(config.TEMPLATE_FIELDS)


@dataclass
class ExtractionResult:
    """Outcome of extracting one page image."""

    fields: dict = field(default_factory=dict)
    confidence_scores: dict[str, int] = field(default_factory=dict)
    model: str = ""
    processing_time: float = 0.0
    success: bool = False
    error: str | None = None


class ExtractionEngine:
    """Extracts fields/values from a page image via the routed model."""

    def __init__(
        self,
        client=None,
        max_image_side: int = MAX_IMAGE_SIDE,
        template_fields: list[str] | None = None,
    ) -> None:
        """Accepts an already-connected client so many pages can share one
        connection, plus the field list to lock extraction to."""
        self._client = client
        self.max_image_side = max_image_side
        self.template_fields = list(
            template_fields if template_fields is not None else config.TEMPLATE_FIELDS
        )

    def extract(self, image: Image.Image, decision: RoutingDecision) -> ExtractionResult:
        """Sends one page to the routed model and turns the reply into fields
        with confidence scores - the actual data-extraction feature. Failures
        land in result.error instead of raising, so one bad page never stops
        the pipeline."""
        result = ExtractionResult(model=decision.model)
        started = time.perf_counter()
        try:
            payload = self._to_base64_png(image)
            response = self._get_client().chat.completions.create(
                model=decision.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{payload}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=1000,
            )
            raw = response.choices[0].message.content or ""
            fields, confidences = self._parse_json_object(raw)
            result.fields = fields
            result.confidence_scores = confidences
            result.success = True
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error("Extraction failed (%s): %s", decision.model, exc)
        result.processing_time = round(time.perf_counter() - started, 2)
        return result

    def _get_client(self):
        """Creates the gateway client lazily so single-page callers do not have
        to build one themselves."""
        if self._client is None:
            self._client = ModelRouter.create_client()
        return self._client

    def _to_base64_png(self, image: Image.Image) -> str:
        """Downscales huge pages before sending, to keep request size and token
        cost bounded without losing readable detail."""
        img = image.convert("RGB")
        if max(img.size) > self.max_image_side:
            scale = self.max_image_side / max(img.size)
            img = img.resize(
                (round(img.width * scale), round(img.height * scale))
            )
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _parse_json_object(raw: str) -> tuple[dict, dict[str, int]]:
        """Reads the model reply defensively - strips code fences and picks the
        first JSON object - because models often wrap JSON in extra text, and a
        parse failure should degrade to empty fields, not an exception."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.warning("No JSON object found in model reply: %.120r", raw)
            return {}, {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse failed (%s): %.120r", exc, raw)
            return {}, {}

        if not isinstance(data, dict):
            return {"result": data}, {}

        fields: dict = {}
        confidence_scores: dict[str, int] = {}

        for field_name, field_data in data.items():
            if isinstance(field_data, dict) and "value" in field_data:
                fields[field_name] = field_data["value"]
                confidence = field_data.get("confidence")
                if isinstance(confidence, (int, float)) and 0 <= confidence <= 100:
                    confidence_scores[field_name] = int(confidence)
                else:
                    confidence_scores[field_name] = 0
            else:
                fields[field_name] = field_data
                confidence_scores[field_name] = 0

        return fields, confidence_scores
