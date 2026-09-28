"""
Extraction Layer
----------------
Sends each enhanced page image to the model selected by the Model Router
and extracts fields and values as structured JSON.

    Enhanced image + RoutingDecision -> gateway vision model -> fields

The prompt itself lives in src/prompts.py - this file only handles the
mechanics: sending the request, shrinking the image, parsing the reply.

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
from src.prompts import EXTRACTION_PROMPT
from src.router import ModelRouter, RoutingDecision

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 2048


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
