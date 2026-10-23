import base64
import io
import json
import logging
from dataclasses import dataclass, field

from PIL import Image

from src import console
from src.budget import RetryBudget
from src.prompts import EXTRACTION_PROMPT
from src.router import ModelRouter, RoutingDecision

logger = logging.getLogger(__name__)

MAX_IMAGE_SIDE = 2048


@dataclass
class ExtractionResult:
    fields: dict = field(default_factory=dict)
    confidence_scores: dict[str, int] = field(default_factory=dict)
    model: str = ""
    success: bool = False
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    retries_used: int = 0


class ExtractionEngine:
    def __init__(
        self,
        client=None,
        max_image_side: int = MAX_IMAGE_SIDE,
    ) -> None:
        self._client = client
        self.max_image_side = max_image_side

    async def extract(
        self,
        image: Image.Image,
        decision: RoutingDecision,
        retry_budget: RetryBudget,
        subject: str,
    ) -> ExtractionResult:
        result = ExtractionResult(model=decision.model)
        payload = self._to_base64_png(image)
        page_retries = 0
        while True:
            try:
                response = await self._get_client().chat.completions.create(
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
                result.fields, result.confidence_scores = self._parse_json_object(
                    response.choices[0].message.content or ""
                )
                result.success = True
                usage = getattr(response, "usage", None)
                result.input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                result.output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                break
            except Exception as exc:
                result.error = f"{type(exc).__name__}: {exc}"
                if not retry_budget.take_retry(page_retries):
                    break
                page_retries += 1
                result.retries_used = page_retries
                console.emit(
                    subject,
                    "extract",
                    "RETRY",
                    f"{result.error}; retry {page_retries} of {retry_budget.page_limit}"
                    f" (document retries left: "
                    f"{retry_budget.document_limit - retry_budget.retries_used})",
                )
        return result

    def _get_client(self):
        if self._client is None:
            self._client = ModelRouter.create_async_client()
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
