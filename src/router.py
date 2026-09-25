"""
Model Router
------------
Maps the quality assessment (score + tier) of each page to the
appropriate extraction model.

Routing table (from .env):
    clear        (>80)   -> TIER_CLEAR_MODEL
    blurry       (50-80) -> TIER_BLURRY_MODEL
    very_blurry  (<50)   -> TIER_VERY_BLURRY_MODEL

The router itself is a pure, local decision - no API call is needed for
routing. `create_client()` builds the OpenAI-compatible gateway client
used by extraction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src import config
from src.quality import QualityAssessment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = config.TIER_MODEL_MAP.get("very_blurry", "")


@dataclass
class RoutingDecision:
    """The model selected for one page, with the reason why."""

    model: str
    tier: str
    score: float
    reason: str


class ModelRouter:
    """Selects the extraction model for a page from its quality tier."""

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
            reason = (
                f"tier '{assessment.tier}' has no model configured "
                f"-> fallback to default model '{self.default_model}'"
            )
            logger.warning(
                "No model configured for tier '%s'; falling back to %s",
                assessment.tier,
                self.default_model,
            )
            model = self.default_model
        else:
            reason = (
                f"tier '{assessment.tier}' (score {assessment.score}) -> {model}"
            )
        return RoutingDecision(
            model=model,
            tier=assessment.tier,
            score=assessment.score,
            reason=reason,
        )

    @staticmethod
    def create_client():
        from openai import OpenAI

        return OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL)
