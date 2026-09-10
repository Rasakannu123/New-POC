"""
Extraction Layer (Core Component #6)
------------------------------------
Sends each enhanced page image to the model selected by the Model Router
and extracts the top important fields and values as structured JSON.

    Enhanced image + RoutingDecision -> gateway vision model -> fields

- Uses the OpenAI-compatible gateway from config (loaded from .env).
- Only the top important "field: value" pairs are requested (max 10).
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

from src.doc_extraction.layers.router import ModelRouter, RoutingDecision

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 2048
MAX_FIELDS = 10

EXTRACTION_PROMPT = (
    "You are a document data-extraction engine. Examine this document page "
    f"image and extract ONLY the top most important fields and their values "
    f"(at most {MAX_FIELDS} fields - e.g. document type, dates, names, "
    "amounts, reference numbers, addresses). "
    'Return ONLY a valid JSON object with this exact format: '
    '{"field_name": {"value": "extracted_value", "confidence": 85}}. '
    "The confidence must be an integer 0-100 indicating your certainty. "
    "No markdown, no code fences, no explanations. "
    'If the page contains no meaningful fields, return exactly: {}'
)


@dataclass
class ExtractionResult:
    """Outcome of extracting one page image."""

    fields: dict = field(default_factory=dict)
    confidence_scores: dict[str, int] = field(default_factory=dict)
    model: str = ""
    processing_time: float = 0.0
    success: bool = False
    error: str | None = None
    raw_response: str = ""


class ExtractionEngine:
    """Extracts top fields/values from a page image via the routed model."""

    def __init__(self, client=None, max_image_side: int = MAX_IMAGE_SIDE) -> None:
        self._client = client
        self.max_image_side = max_image_side

    def extract(self, image: Image.Image, decision: RoutingDecision) -> ExtractionResult:
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
            result.raw_response = raw
            result.fields, result.confidence_scores = self._parse_json_object(raw)
            result.success = True
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error("Extraction failed (%s): %s", decision.model, exc)
        result.processing_time = round(time.perf_counter() - started, 2)
        return result

    def _get_client(self):
        if self._client is None:
            self._client = ModelRouter.create_client()
        return self._client

    def _to_base64_png(self, image: Image.Image) -> str:
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