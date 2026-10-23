from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src import config, console
from src.budget import RetryBudget, TokenBudget
from src.conversion import ImageConversionLayer
from src.extraction import ExtractionEngine
from src.identity import allocate_document_id, page_id_for
from src.latency import LatencyTracker
from src.preprocessing import ImagePreprocessingEngine
from src.quality import QualityAssessment, QualityAssessmentEngine
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

TOKEN_LIMIT_MESSAGE = (
    "Token limit has been reached for this document. "
    "Further model calls have been stopped."
)


def _build_gates() -> dict[str, asyncio.Semaphore | threading.Semaphore]:
    return {
        node: (asyncio.Semaphore if node == "extract" else threading.Semaphore)(max(1, limit))
        for node, limit in config.FEATURE_CONCURRENCY.items()
    }


def _start(subject: str, node: str) -> None:
    console.emit(subject, node, "STARTED", FEATURES[node])


def _done(subject: str, node: str, timing, detail: str = "") -> None:
    console.emit(
        subject,
        node,
        timing.status,
        detail or FEATURES[node],
        timing.seconds,
        timing.threshold,
    )


def _report_token_limit(ctx: DocumentContext) -> None:
    if not ctx.token_limit_reported:
        ctx.token_limit_reported = True
        console.emit(ctx.document_id, "tokens", "STOPPED", TOKEN_LIMIT_MESSAGE)


def _page_record(ctx: DocumentContext, page_number: int, page_id: str, **fields) -> dict:
    record = {
        "page": page_number,
        "page_id": page_id,
        "image": None,
        "status": "stopped",
        "quality_score": None,
        "quality_tier": None,
        "model": None,
        "extracted_fields": {},
        "field_confidence_scores": {},
        "success": False,
        "error": None,
        "processing_time": ctx.latency.subject_total(page_id),
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "document_total_tokens": ctx.token_budget.used,
        "retries_used": 0,
    }
    record.update(fields)
    return record


@dataclass
class DocumentContext:
    pdf_path: Path
    document_id: str
    conversion: ImageConversionLayer
    preprocessing: ImagePreprocessingEngine
    quality: QualityAssessmentEngine
    router: ModelRouter
    extractor: ExtractionEngine
    token_budget: TokenBudget
    retry_budget: RetryBudget
    latency: LatencyTracker
    gates: dict[str, asyncio.Semaphore | threading.Semaphore]
    token_limit_reported: bool = False

    @classmethod
    def create(cls, pdf_path: Path) -> DocumentContext:
        return cls(
            pdf_path=pdf_path,
            document_id=allocate_document_id(),
            conversion=ImageConversionLayer(dpi=config.DPI),
            preprocessing=ImagePreprocessingEngine(),
            quality=QualityAssessmentEngine(),
            router=ModelRouter(),
            extractor=ExtractionEngine(),
            token_budget=TokenBudget(config.DOCUMENT_TOKEN_LIMIT),
            retry_budget=RetryBudget(
                config.LLM_PAGE_RETRY_LIMIT, config.LLM_DOCUMENT_RETRY_LIMIT
            ),
            latency=LatencyTracker(config.LATENCY_THRESHOLDS),
            gates=_build_gates(),
        )


class PageState(TypedDict, total=False):
    ctx: DocumentContext
    page_number: int
    page_id: str
    image: object
    enhanced_image: object
    assessment: dict
    routing: dict
    record: dict


class DocumentState(TypedDict, total=False):
    ctx: DocumentContext
    images: list
    page_results: list
    output_json: str
    error: str | None


def convert_node(state: DocumentState) -> dict:
    ctx = state["ctx"]
    _start(ctx.document_id, "convert")
    with ctx.latency.measure("convert", ctx.document_id) as timing:
        converted = ctx.conversion.convert_pages(ctx.pdf_path)
    message = ""
    if not converted.success:
        message = converted.error or "conversion failed"
    elif converted.page_count == 0:
        message = "document has no pages"
    if message:
        _done(ctx.document_id, "convert", timing, f"failed; {message}")
        return {"error": message}
    _done(
        ctx.document_id,
        "convert",
        timing,
        f"{FEATURES['convert']}; {converted.page_count} "
        f"page{'s' if converted.page_count != 1 else ''}",
    )
    return {"images": converted.pages}


def enhance_node(state: PageState) -> dict:
    ctx = state["ctx"]
    page_id = state["page_id"]
    with ctx.gates["enhance"]:
        _start(page_id, "enhance")
        with ctx.latency.measure("enhance", page_id) as timing:
            image = ctx.preprocessing.enhance(state["image"])
        _done(page_id, "enhance", timing)
        return {"enhanced_image": image}


def assess_node(state: PageState) -> dict:
    ctx = state["ctx"]
    page_id = state["page_id"]
    with ctx.gates["assess"]:
        _start(page_id, "assess")
        with ctx.latency.measure("assess", page_id) as timing:
            result = ctx.quality.assess(state["enhanced_image"])
        _done(page_id, "assess", timing, f"score {result.score} -> {result.tier}")
        return {
            "assessment": {
                "page_id": page_id,
                "score": result.score,
                "tier": result.tier,
            }
        }


def route_node(state: PageState) -> dict:
    ctx = state["ctx"]
    assessment = state["assessment"]
    page_id = state["page_id"]
    with ctx.gates["route"]:
        _start(page_id, "route")
        with ctx.latency.measure("route", page_id) as timing:
            decision = ctx.router.route(
                QualityAssessment(
                    score=assessment["score"], tier=assessment["tier"]
                ),
            )
        _done(page_id, "route", timing, f"model {decision.model}")
        return {
            "routing": {
                "page_id": page_id,
                "model": decision.model,
                "tier": decision.tier,
                "score": decision.score,
            }
        }


async def extract_node(state: PageState) -> dict:
    ctx = state["ctx"]
    page_id = state["page_id"]
    routing = state["routing"]
    decision = RoutingDecision(
        model=routing["model"],
        tier=routing["tier"],
        score=routing["score"],
    )

    async with ctx.gates["extract"]:
        if ctx.token_budget.exhausted:
            _report_token_limit(ctx)
            return {
                "record": _page_record(
                    ctx,
                    state["page_number"],
                    page_id,
                    error=TOKEN_LIMIT_MESSAGE,
                    quality_score=routing["score"],
                    quality_tier=routing["tier"],
                )
            }
        _start(page_id, "extract")
        with ctx.latency.measure("extract", page_id) as timing:
            result = await ctx.extractor.extract(
                state["enhanced_image"],
                decision,
                retry_budget=ctx.retry_budget,
                subject=page_id,
            )
        usage = ctx.token_budget.record(result.input_tokens, result.output_tokens)

        status = "completed" if result.success else "failed"
        detail = [
            status,
            f"tokens {usage.total_tokens} (input {usage.input_tokens}, output {usage.output_tokens})",
            f"document total {ctx.token_budget.used} tokens",
        ]
        if result.error:
            detail.insert(1, result.error)
        if result.retries_used:
            detail.append(f"retries {result.retries_used}")
        _done(page_id, "extract", timing, "; ".join(detail))

    if ctx.token_budget.exhausted:
        _report_token_limit(ctx)
    return {
        "record": _page_record(
            ctx,
            state["page_number"],
            page_id,
            image=f"page-{state['page_number']:02d}.{config.IMAGE_FORMAT}",
            status=status,
            quality_score=routing["score"],
            quality_tier=routing["tier"],
            model=result.model,
            extracted_fields=result.fields,
            field_confidence_scores=result.confidence_scores,
            success=result.success,
            error=result.error,
            token_usage={
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            },
            document_total_tokens=ctx.token_budget.used,
            retries_used=result.retries_used,
        )
    }


async def pages_node(state: DocumentState) -> dict:
    ctx = state["ctx"]
    images = state["images"]

    async def process_page(number: int) -> tuple[dict, object]:
        page_id = page_id_for(ctx.document_id, number)
        if ctx.token_budget.exhausted:
            _report_token_limit(ctx)
            return _page_record(ctx, number, page_id, error=TOKEN_LIMIT_MESSAGE), None
        try:
            page_state = await PAGE_GRAPH.ainvoke(
                {
                    "ctx": ctx,
                    "page_number": number,
                    "page_id": page_id,
                    "image": images[number - 1],
                }
            )
        except Exception as exc:
            logger.exception("Pipeline crashed for %s", page_id)
            return (
                _page_record(ctx, number, page_id, status="failed", error=str(exc)),
                None,
            )
        if page_state.get("record"):
            return page_state["record"], page_state.get("enhanced_image")
        return (
            _page_record(
                ctx, number, page_id, status="failed", error="page processing failed"
            ),
            None,
        )

    results = await asyncio.gather(
        *(process_page(number) for number in range(1, len(images) + 1))
    )
    return {"page_results": list(results)}


def output_node(state: DocumentState) -> dict:
    ctx = state["ctx"]
    results = state["page_results"]
    pages = sorted((record for record, _ in results), key=lambda r: r["page"])
    if not pages:
        return {"output_json": ""}
    images = {
        record["page"]: image
        for record, image in results
        if image is not None
    }

    directory = config.OUTPUT_DIR / ctx.pdf_path.stem
    directory.mkdir(parents=True, exist_ok=True)
    _start(ctx.document_id, "output")
    with ctx.latency.measure("output", ctx.document_id) as timing:
        for record in pages:
            image = images.get(record["page"])
            if image is not None and record["image"]:
                image.save(directory / record["image"])
        output_json = directory / "result.json"
        output_json.write_text(
            json.dumps(
                {
                    "document": ctx.pdf_path.name,
                    "document_id": ctx.document_id,
                    "pages": pages,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    _done(
        ctx.document_id,
        "output",
        timing,
        f"{FEATURES['output']}; {len(pages)} "
        f"page{'s' if len(pages) != 1 else ''}; result.json",
    )
    return {"output_json": str(output_json)}


def build_page_graph() -> StateGraph:
    builder = StateGraph(PageState)
    builder.add_node("enhance", enhance_node)
    builder.add_node("assess", assess_node)
    builder.add_node("route", route_node)
    builder.add_node("extract", extract_node)

    builder.add_edge(START, "enhance")
    builder.add_edge("enhance", "assess")
    builder.add_edge("assess", "route")
    builder.add_edge("route", "extract")
    builder.add_edge("extract", END)
    return builder


def build_document_graph() -> StateGraph:
    builder = StateGraph(DocumentState)
    builder.add_node("convert", convert_node)
    builder.add_node("pages", pages_node)
    builder.add_node("output", output_node)
    builder.add_edge(START, "convert")
    builder.add_edge("convert", "pages")
    builder.add_edge("pages", "output")
    builder.add_edge("output", END)
    return builder


PAGE_GRAPH = build_page_graph().compile()


def _finalize(output_json: str, ctx: DocumentContext, wall_seconds: float) -> None:
    path = Path(output_json)
    record = json.loads(path.read_text(encoding="utf-8"))
    total = ctx.latency.total()
    record["wall_processing_time"] = wall_seconds
    record["total_processing_time"] = total
    record["node_latency"] = ctx.latency.node_totals()
    record["token_usage"] = {
        "limit": ctx.token_budget.limit,
        "used": ctx.token_budget.used,
        "limit_reached": ctx.token_budget.exhausted,
    }
    record["retry_usage"] = {
        "page_limit": ctx.retry_budget.page_limit,
        "document_limit": ctx.retry_budget.document_limit,
        "retries_used": ctx.retry_budget.retries_used,
    }
    for page in record["pages"]:
        page["total_processing_time"] = total
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _report_latency(ctx: DocumentContext, wall_seconds: float) -> None:
    totals = ctx.latency.node_totals()
    breakdown = "; ".join(
        f"{node} {seconds:.2f}s" for node, seconds in totals.items()
    )
    console.emit(
        ctx.document_id,
        "summary",
        "COMPLETED",
        f"node work {ctx.latency.total():.2f}s; node times: {breakdown}",
        wall_seconds,
    )


async def run_async(pdf_files: list[Path] | None = None) -> int:
    console.install()
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if pdf_files is None:
        pdf_files = sorted(
            path
            for path in config.INPUT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
    if not pdf_files:
        console.emit(
            "run", "summary", "EMPTY", f"No PDF documents found in '{config.INPUT_DIR}'."
        )
        return 0

    graph = build_document_graph().compile()
    document_semaphore = asyncio.Semaphore(
        max(1, config.MAX_CONCURRENT_DOCUMENTS)
    )

    async def process_one(pdf_path: Path) -> bool:
        ctx = DocumentContext.create(pdf_path)
        async with document_semaphore:
            wall_started = time.perf_counter()
            console.emit(ctx.document_id, "document", "STARTED", pdf_path.name)
            try:
                state = await graph.ainvoke({"ctx": ctx})
            except Exception as exc:
                logger.exception("Pipeline crashed for %s", ctx.document_id)
                console.emit(ctx.document_id, "document", "FAILED", str(exc))
                return False
        wall_seconds = round(time.perf_counter() - wall_started, 2)
        if state.get("error"):
            console.emit(ctx.document_id, "document", "FAILED", state["error"])
            return False
        output_json = state.get("output_json", "")
        if output_json:
            _finalize(output_json, ctx, wall_seconds)
        _report_latency(ctx, wall_seconds)
        console.emit(ctx.document_id, "result", "SAVED", output_json or "-")
        return True

    results = await asyncio.gather(*(process_one(pdf) for pdf in pdf_files))
    failed = results.count(False)

    console.emit(
        "run",
        "summary",
        "COMPLETED",
        f"{len(pdf_files) - failed} succeeded, {failed} failed",
    )
    return 1 if failed else 0


def run(pdf_files: list[Path] | None = None) -> int:
    return asyncio.run(run_async(pdf_files))
