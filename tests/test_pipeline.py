"""Smoke tests for the parsing/routing logic (no external services)."""

from __future__ import annotations

from src.doc_extraction.layers.extraction import ExtractionEngine
from src.doc_extraction.layers.quality import QualityAssessment
from src.doc_extraction.layers.router import ModelRouter


def test_parse_json_object_with_confidence():
    fields, conf = ExtractionEngine._parse_json_object(
        '{"total": {"value": "100", "confidence": 90}}'
    )
    assert fields == {"total": "100"}
    assert conf == {"total": 90}


def test_parse_json_object_strips_code_fences():
    fields, _ = ExtractionEngine._parse_json_object(
        '```json\n{"a": {"value": "b", "confidence": 50}}\n```'
    )
    assert fields == {"a": "b"}


def test_parse_json_object_empty():
    fields, conf = ExtractionEngine._parse_json_object("{}")
    assert fields == {}
    assert conf == {}


def test_router_maps_tiers():
    router = ModelRouter(
        tier_model_map={"clear": "m", "blurry": "n", "very_blurry": "o"},
        default_model="o",
    )
    decision = router.route(
        QualityAssessment(score=95.0, tier="clear")
    )
    assert decision.model == "m"