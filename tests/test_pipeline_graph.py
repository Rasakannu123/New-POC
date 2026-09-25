"""Tests for the LangGraph demo pipeline."""

import json
from pathlib import Path

from PIL import Image

from src.doc_extraction import config
from src.doc_extraction.pipeline_graph import (
    FEATURES,
    build_graph,
    output_node,
)


def test_graph_has_one_node_per_feature():
    builder = build_graph()
    assert set(builder.nodes) == set(FEATURES)


def test_feature_names_match_the_demo_scope():
    assert set(FEATURES.values()) == {
        "PDF-to-Images converter",
        "Image enhancement",
        "Quality assessment of images",
        "Model router based on the quality score",
        "Data extraction",
        "JSON output",
    }


def test_output_node_writes_json_and_images(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    state = {
        "pdf_path": "data/input/demo.pdf",
        "enhanced": [Image.new("RGB", (4, 4))],
        "assessments": [{"page": 1, "score": 88.0, "tier": "clear"}],
        "extractions": [
            {
                "page": 1,
                "model": "m",
                "extracted_fields": {"invoice_number": "123"},
                "field_confidence_scores": {"invoice_number": 90},
                "success": True,
                "error": None,
            }
        ],
    }

    update = output_node(state)

    record = json.loads(Path(update["output_json"]).read_text(encoding="utf-8"))
    assert record["document"] == "demo.pdf"
    assert record["pages"][0]["quality_score"] == 88.0
    assert record["pages"][0]["extracted_fields"] == {"invoice_number": "123"}
    assert (tmp_path / "demo" / "page-01.png").is_file()
