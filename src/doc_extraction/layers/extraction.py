"""
Extraction Layer (Core Component #6)
------------------------------------
Sends each enhanced page image to the model selected by the Model Router
and extracts the top important fields and values as structured JSON.

    Enhanced image + RoutingDecision -> gateway vision model -> fields

- Uses the OpenAI-compatible gateway from config (loaded from .env).
- Extraction is locked to the configured template fields when
  config.TEMPLATE_FIELDS is set; missing fields are returned as null.
  Otherwise the top important fields are requested (max 10).
- Images are downscaled to max 2048 px on the long side before sending.
- Responses are parsed robustly (code fences stripped, first JSON object
  extracted). A failed page never stops the pipeline.
- `extract_async()` is the network-bound path used by the concurrent
  pipeline; `extract()` remains for synchronous callers.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time
from dataclasses import dataclass, field

from PIL import Image

from src.doc_extraction import config
from src.doc_extraction.layers.router import ModelRouter, RoutingDecision
from src.doc_extraction.prompts import EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 2048


@dataclass
class ExtractionResult:
    """Outcome of extracting one page image."""

    fields: dict = field(default_factory=dict)
    confidence_scores: dict[str, int] = field(default_factory=dict)
    helper_values: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    processing_time: float = 0.0
    success: bool = False
    error: str | None = None
    raw_response: str = ""


class ExtractionEngine:
    """Extracts top fields/values from a page image via the routed model."""

    def __init__(
        self,
        client=None,
        async_client=None,
        max_image_side: int = MAX_IMAGE_SIDE,
        helper_fields: list[str] | None = None,
        template_fields: list[str] | None = None,
    ) -> None:
        self._client = client
        self._async_client = async_client
        self.max_image_side = max_image_side
        self.helper_fields = list(
            helper_fields if helper_fields is not None else config.MULTI_DOC_FIELDS
        )
        self.template_fields = list(
            template_fields if template_fields is not None else config.TEMPLATE_FIELDS
        )

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
            self._capture_usage(response, result)
            fields, confidences = self._parse_json_object(raw)
            self._separate_helper_fields(fields, confidences, result)
            result.success = True
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error("Extraction failed (%s): %s", decision.model, exc)
        result.processing_time = round(time.perf_counter() - started, 2)
        return result

    async def extract_async(
        self, image: Image.Image, decision: RoutingDecision
    ) -> ExtractionResult:
        """Extract fields from one page image without blocking the event loop."""
        result = ExtractionResult(model=decision.model)
        started = time.perf_counter()
        try:
            payload = self._to_base64_png(image)
            response = await self._get_async_client().chat.completions.create(
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
            self._capture_usage(response, result)
            fields, confidences = self._parse_json_object(raw)
            self._separate_helper_fields(fields, confidences, result)
            result.success = True
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            logger.error("Extraction failed (%s): %s", decision.model, exc)
        result.processing_time = round(time.perf_counter() - started, 2)
        return result

    @staticmethod
    def _capture_usage(response, result: ExtractionResult) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        result.input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        result.output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

    def _separate_helper_fields(
        self, fields: dict, confidences: dict[str, int], result: ExtractionResult
    ) -> None:
        for name in self.helper_fields:
            if name in fields:
                result.helper_values[name] = fields[name]
                if name not in self.template_fields:
                    fields.pop(name)
                    confidences.pop(name, None)
        result.fields = fields
        result.confidence_scores = confidences

    def _get_client(self):
        if self._client is None:
            self._client = ModelRouter.create_client()
        return self._client

    def _get_async_client(self):
        if self._async_client is None:
            self._async_client = ModelRouter.create_async_client()
        return self._async_client

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