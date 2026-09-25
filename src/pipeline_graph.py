"""
LangGraph demo pipeline
-----------------------
One PDF is one LangGraph run. The graph has six nodes - one per feature -
and every node prints the feature it is working on to the terminal:

    convert -> enhance -> assess -> route -> extract -> output -> END

Output per document (data/output/<name>/):
    page-01.png ...  enhanced page images
    result.json      extracted fields + metadata
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src import config
from src.conversion import ImageConversionLayer
from src.extraction import ExtractionEngine
from src.preprocessing import ImagePreprocessingEngine
from src.quality import (
    QualityAssessment,
    QualityAssessmentEngine,
)
from src.router import ModelRouter, RoutingDecision

logger = logging.getLogger("pipeline")

FEATURES = {
    "convert": "PDF-to-Images converter",
    "enhance": "Image enhancement",
    "assess": "Quality assessment of images",
    "route": "Model router based on the quality score",
    "extract": "Data extraction",
    "output": "JSON output",
}


class PipelineState(TypedDict, total=False):
    """The data handed from node to node - everything a later node needs, and
    nothing more, so the state stays small and easy to follow."""

    pdf_path: str
    images: list
    enhanced: list
    assessments: list[dict]
    routing: list[dict]
    extractions: list[dict]
    output_json: str
    error: str | None


def _show(node: str) -> None:
    """Prints the feature name so the terminal always shows what the pipeline
    is working on right now - the demo's only progress display."""
    print(f"  [{node}] {FEATURES[node]}")


def convert_node(state: PipelineState) -> dict:
    """Feature 1 - turns the PDF into page images, because every later node
    works per page image. A broken PDF sets the error that ends the run."""
    _show("convert")
    result = ImageConversionLayer(dpi=config.DPI).convert_pages(state["pdf_path"])
    if not result.success:
        return {"error": result.error or "conversion failed"}
    if result.page_count == 0:
        return {"error": "document has no pages"}
    return {"images": result.pages}


def enhance_node(state: PipelineState) -> dict:
    """Feature 2 - cleans up each page image so OCR and the vision model read
    it as clearly as possible."""
    _show("enhance")
    engine = ImagePreprocessingEngine()
    return {"enhanced": [engine.enhance(image) for image in state["images"]]}


def assess_node(state: PipelineState) -> dict:
    """Feature 3 - scores every page 0-100 and assigns a quality tier; the
    scores are printed because they explain every later routing choice."""
    _show("assess")
    engine = QualityAssessmentEngine()
    assessments = []
    for page_number, image in enumerate(state["enhanced"], start=1):
        result = engine.assess(image)
        assessments.append(
            {"page": page_number, "score": result.score, "tier": result.tier}
        )
        print(f"       page {page_number}: score {result.score} -> {result.tier}")
    return {"assessments": assessments}


def route_node(state: PipelineState) -> dict:
    """Feature 4 - maps each page's tier to an extraction model, so clear pages
    use the cheap model and only hard pages pay for the strong one."""
    _show("route")
    router = ModelRouter()
    routing = []
    for item in state["assessments"]:
        decision = router.route(
            QualityAssessment(score=item["score"], tier=item["tier"])
        )
        routing.append(
            {
                "page": item["page"],
                "model": decision.model,
                "tier": decision.tier,
                "score": decision.score,
                "reason": decision.reason,
            }
        )
        print(f"       page {item['page']}: {decision.model}")
    return {"routing": routing}


def extract_node(state: PipelineState) -> dict:
    """Feature 5 - the model call that turns each page image into fields and
    confidence scores; one entry per page so results stay page-aligned."""
    _show("extract")
    engine = ExtractionEngine()
    routing = {item["page"]: item for item in state["routing"]}
    extractions = []
    for page_number, image in enumerate(state["enhanced"], start=1):
        item = routing[page_number]
        decision = RoutingDecision(
            model=item["model"],
            tier=item["tier"],
            score=item["score"],
            reason=item["reason"],
        )
        result = engine.extract(image, decision)
        extractions.append(
            {
                "page": page_number,
                "model": result.model,
                "extracted_fields": result.fields,
                "field_confidence_scores": result.confidence_scores,
                "success": result.success,
                "error": result.error,
            }
        )
        print(f"       page {page_number}: {'ok' if result.success else 'failed'}")
    return {"extractions": extractions}


def output_node(state: PipelineState) -> dict:
    """Feature 6 - writes the enhanced page images and result.json; this file
    is the final data the web UI displays, so score, tier, model and fields
    are merged per page here."""
    _show("output")
    pdf = Path(state["pdf_path"])
    directory = config.OUTPUT_DIR / pdf.stem
    directory.mkdir(parents=True, exist_ok=True)

    pages = []
    for item in state["extractions"]:
        index = item["page"] - 1
        image_name = f"page-{item['page']:02d}.{config.IMAGE_FORMAT}"
        state["enhanced"][index].save(directory / image_name)
        assessment = state["assessments"][index]
        pages.append(
            {
                "page": item["page"],
                "image": image_name,
                "quality_score": assessment["score"],
                "quality_tier": assessment["tier"],
                "model": item["model"],
                "extracted_fields": item["extracted_fields"],
                "field_confidence_scores": item["field_confidence_scores"],
                "success": item["success"],
                "error": item["error"],
            }
        )

    record = {"document": pdf.name, "pages": pages}
    output_json = directory / "result.json"
    output_json.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"output_json": str(output_json)}


def _after_convert(state: PipelineState) -> str:
    """Routes straight to the end when conversion failed - the other nodes
    cannot do anything without page images."""
    return "end" if state.get("error") else "enhance"


def build_graph() -> StateGraph:
    """Wires the six feature nodes into one LangGraph pipeline - the graph is
    what makes the run order and the per-feature progress explicit."""
    builder = StateGraph(PipelineState)
    builder.add_node("convert", convert_node)
    builder.add_node("enhance", enhance_node)
    builder.add_node("assess", assess_node)
    builder.add_node("route", route_node)
    builder.add_node("extract", extract_node)
    builder.add_node("output", output_node)
    builder.add_edge(START, "convert")
    builder.add_conditional_edges(
        "convert", _after_convert, {"enhance": "enhance", "end": END}
    )
    builder.add_edge("enhance", "assess")
    builder.add_edge("assess", "route")
    builder.add_edge("route", "extract")
    builder.add_edge("extract", "output")
    builder.add_edge("output", END)
    return builder


def run(pdf_files: list[Path] | None = None) -> int:
    """Runs the graph once per PDF (or for the given files) and returns a shell
    exit code, so both main.py and the web UI share the exact same pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if pdf_files is None:
        pdf_files = sorted(
            path
            for path in config.INPUT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
    if not pdf_files:
        print(f"No PDF documents found in '{config.INPUT_DIR}'.")
        return 0

    graph = build_graph().compile()
    failed = 0
    for pdf_path in pdf_files:
        print(f"\nProcessing: {pdf_path.name}")
        state = graph.invoke({"pdf_path": str(pdf_path)})
        if state.get("error"):
            failed += 1
            print(f"  !! FAILED: {state['error']}")
        else:
            print(f"  => {state['output_json']}")

    print(f"\nDone. {len(pdf_files) - failed} succeeded, {failed} failed.")
    return 1 if failed else 0
