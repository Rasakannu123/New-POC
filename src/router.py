import logging
from dataclasses import dataclass

from src import config
from src.quality import QualityAssessment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = config.TIER_MODEL_MAP.get("very_blurry", "")


@dataclass
class RoutingDecision:
    model: str
    tier: str
    score: float


class ModelRouter:
    def __init__(
        self,
        tier_model_map: dict[str, str] | None = None,
        default_model: str = DEFAULT_MODEL,
    ) -> None:
        self.tier_model_map = dict(tier_model_map or config.TIER_MODEL_MAP)
        self.default_model = default_model

    def route(self, assessment: QualityAssessment) -> RoutingDecision:
        model = self.tier_model_map.get(assessment.tier)
        if not model:
            logger.warning(
                "No model configured for tier '%s'; falling back to %s",
                assessment.tier,
                self.default_model,
            )
            model = self.default_model
        return RoutingDecision(
            model=model,
            tier=assessment.tier,
            score=assessment.score,
        )

    @staticmethod
    def create_async_client():
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
