"""
LangGraph demo pipeline
-----------------------
One document is one asynchronous LangGraph run. Several documents are
processed at the same time (up to MAX_CONCURRENT_DOCUMENTS from .env) and
every document works through its pages one by one - as soon as one page is
done the next page starts, and a document's results are delivered the moment
that document finishes, without waiting for any other document.

Per page the graph runs:

    convert -> enhance -> assess -> route -> extract -> (next page | output)

Every document gets a unique document ID ("0001") and every page a page ID
("0001/01"). Processing, routing and logging identify work by these IDs -
never by file name - and both IDs are stored in the result metadata.

Each node measures its latency against a configurable threshold (Task 3), the
total processing time of the document is reported and stored in the page
metadata (Task 4), failed model calls are retried within per-page and
per-document limits (Task 5), and the cumulative token usage of the document
stops all further model calls once its token limit is reached (Task 6).

Output per document (data/output/<name>/):
    page-01.png ...  enhanced page images
    result.json      extracted fields + metadata (IDs, latency, tokens, retries)

Every terminal message uses one aligned line format (src/console.py):

    TIME | SUBJECT | NODE | STATUS | LATENCY | DETAIL

so the output stays readable while several documents interleave.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
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


@dataclass
class DocumentContext:
    """Everything one document run needs besides page data: the engines, the
    document identity, the token/retry budgets and the latency tracker. All
    nodes share it, so budgets and timings accumulate across the document."""

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
    page_ids: list[str] = field(default_factory=list)
    enhanced_pages: list = field(default_factory=list)
    token_limit_reported: bool = False

    @classmethod
    def create(cls, pdf_path: Path) -> DocumentContext:
        """Builds a fully configured context; the unique document ID is
        allocated here, before processing starts, so it stays stable even
        when documents finish out of order."""
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
        )


class PipelineState(TypedDict, total=False):
    """The data handed from node to node - everything a later node needs, and
    nothing more, so the state stays small and easy to follow."""

    ctx: DocumentContext
    images: list
    page_index: int
    page_records: list[dict]
    enhanced_image: object
    assessment: dict
    routing: dict
    output_json: str
    error: str | None


def _start(subject: str, node: str) -> None:
    """Prints the feature the pipeline is working on right now - the demo's
    only progress display."""
    console.emit(subject, node, "STARTED", FEATURES[node])


def _done(
    subject: str, node: str, timing, detail: str = ""
) -> None:
    """Prints one node's finished line: processing status, latency against
    its threshold, and what the node produced."""
    console.emit(
        subject,
        node,
        timing.status,
        detail or FEATURES[node],
        timing.seconds,
        timing.threshold,
    )


async def convert_node(state: PipelineState) -> dict:
    """Feature 1 - turns the PDF into page images, because every later node
    works per page image. Runs off the event loop so other documents keep
    processing while Poppler renders. A broken PDF is recorded in state and
    reported at the end of the run instead of crashing."""
    ctx = state["ctx"]
    _start(ctx.document_id, "convert")
    with ctx.latency.measure("convert", ctx.document_id) as timing:
        result = await asyncio.to_thread(
            ctx.conversion.convert_pages, ctx.pdf_path
        )
    if not result.success:
        error = result.error or "conversion failed"
        _done(ctx.document_id, "convert", timing, f"failed; {error}")
        return {"error": error}
    if result.page_count == 0:
        _done(ctx.document_id, "convert", timing, "failed; document has no pages")
        return {"error": "document has no pages"}
    ctx.page_ids = [
        page_id_for(ctx.document_id, number)
        for number in range(1, result.page_count + 1)
    ]
    _done(
        ctx.document_id,
        "convert",
        timing,
        f"{FEATURES['convert']}; {result.page_count} "
        f"page{'s' if result.page_count != 1 else ''}",
    )
    return {"images": result.pages, "page_index": 0, "page_records": []}


async def enhance_node(state: PipelineState) -> dict:
    """Feature 2 - cleans up the current page image so OCR and the vision
    model read it as clearly as possible."""
    ctx = state["ctx"]
    index = state["page_index"]
    page_id = ctx.page_ids[index]
    _start(page_id, "enhance")
    with ctx.latency.measure("enhance", page_id) as timing:
        image = await asyncio.to_thread(
            ctx.preprocessing.enhance, state["images"][index]
        )
    ctx.enhanced_pages.append(image)
    _done(page_id, "enhance", timing)
    return {"enhanced_image": image}


async def assess_node(state: PipelineState) -> dict:
    """Feature 3 - scores the current page 0-100 and assigns a quality tier;
    the scores are printed because they explain every later routing choice."""
    ctx = state["ctx"]
    index = state["page_index"]
    page_id = ctx.page_ids[index]
    _start(page_id, "assess")
    with ctx.latency.measure("assess", page_id) as timing:
        result = await asyncio.to_thread(ctx.quality.assess, state["enhanced_image"])
    _done(page_id, "assess", timing, f"score {result.score} -> {result.tier}")
    return {
        "assessment": {
            "page_id": page_id,
            "score": result.score,
            "tier": result.tier,
        }
    }


async def route_node(state: PipelineState) -> dict:
    """Feature 4 - maps the page's tier to an extraction model, so clear pages
    use the cheap model and only hard pages pay for the strong one. The page
    ID is the routing key - never the file name."""
    ctx = state["ctx"]
    assessment = state["assessment"]
    page_id = assessment["page_id"]
    _start(page_id, "route")
    with ctx.latency.measure("route", page_id) as timing:
        decision = await asyncio.to_thread(
            ctx.router.route,
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


async def extract_node(state: PipelineState) -> dict:
    """Feature 5 - the model call that turns the current page image into
    fields and confidence scores. Retries and token usage are accounted per
    page and cumulated per document; when the document's token limit is hit,
    no further page may make a model call."""
    ctx = state["ctx"]
    index = state["page_index"]
    page_id = ctx.page_ids[index]
    _start(page_id, "extract")
    routing = state["routing"]
    decision = RoutingDecision(
        model=routing["model"],
        tier=routing["tier"],
        score=routing["score"],
    )
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
        f"cumulative {ctx.token_budget.used}",
    ]
    if result.error:
        detail.insert(1, result.error)
    if result.retries_used:
        detail.append(f"retries {result.retries_used}")
    _done(page_id, "extract", timing, "; ".join(detail))

    assessment = state["assessment"]
    record = {
        "page": index + 1,
        "page_id": page_id,
        "image": f"page-{index + 1:02d}.{config.IMAGE_FORMAT}",
        "status": status,
        "quality_score": assessment["score"],
        "quality_tier": assessment["tier"],
        "model": result.model,
        "extracted_fields": result.fields,
        "field_confidence_scores": result.confidence_scores,
        "success": result.success,
        "error": result.error,
        "processing_time": ctx.latency.subject_total(page_id),
        "token_usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
        "cumulative_tokens": ctx.token_budget.used,
        "retries_used": result.retries_used,
    }

    more_pages = index + 1 < len(state["images"])
    if more_pages and ctx.token_budget.exhausted and not ctx.token_limit_reported:
        ctx.token_limit_reported = True
        console.emit(ctx.document_id, "tokens", "STOPPED", TOKEN_LIMIT_MESSAGE)

    return {
        "page_records": state["page_records"] + [record],
        "page_index": index + 1,
    }


def _after_convert(state: PipelineState) -> str:
    """A broken document goes straight to output (which writes nothing) so the
    error can be reported; a healthy one starts with its first page."""
    if state.get("error"):
        return "output"
    return "enhance"


def _after_extract(state: PipelineState) -> str:
    """Loops back for the next page - one page at a time - and stops the loop
    early when the document's token limit is reached."""
    ctx = state["ctx"]
    more_pages = state["page_index"] < len(state["images"])
    if more_pages and not ctx.token_budget.exhausted:
        return "enhance"
    return "output"


def output_node(state: PipelineState) -> dict:
    """Feature 6 - writes the enhanced page images and result.json; this file
    is the final data the web UI displays, so score, tier, model and fields
    are merged per page here, and every page ID ends up in the metadata.
    Pages skipped by the token limit are recorded as "stopped". Nothing is
    written when nothing was extracted."""
    records = state.get("page_records")
    if not records:
        return {}
    ctx = state["ctx"]
    _start(ctx.document_id, "output")
    directory = config.OUTPUT_DIR / ctx.pdf_path.stem
    directory.mkdir(parents=True, exist_ok=True)

    with ctx.latency.measure("output", ctx.document_id) as timing:
        pages = list(records)
        for record in records:
            image_name = record["image"]
            ctx.enhanced_pages[record["page"] - 1].save(directory / image_name)
        for number in range(len(records) + 1, len(state["images"]) + 1):
            page_id = ctx.page_ids[number - 1]
            console.emit(
                page_id,
                "extract",
                "STOPPED",
                "no model call made - token limit reached",
            )
            pages.append(
                {
                    "page": number,
                    "page_id": page_id,
                    "image": None,
                    "status": "stopped",
                    "quality_score": None,
                    "quality_tier": None,
                    "model": None,
                    "extracted_fields": {},
                    "field_confidence_scores": {},
                    "success": False,
                    "error": TOKEN_LIMIT_MESSAGE,
                    "processing_time": 0.0,
                    "token_usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                    },
                    "cumulative_tokens": ctx.token_budget.used,
                    "retries_used": 0,
                }
            )

        record = {
            "document": ctx.pdf_path.name,
            "document_id": ctx.document_id,
            "pages": pages,
        }
        output_json = directory / "result.json"
        output_json.write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    _done(
        ctx.document_id,
        "output",
        timing,
        f"{FEATURES['output']}; {len(pages)} "
        f"page{'s' if len(pages) != 1 else ''}; result.json",
    )
    return {"output_json": str(output_json)}


def build_graph() -> StateGraph:
    """Wires the six feature nodes into one LangGraph pipeline - the graph is
    what makes the run order and the per-feature progress explicit. The two
    conditional edges loop the page nodes once per page."""
    builder = StateGraph(PipelineState)
    builder.add_node("convert", convert_node)
    builder.add_node("enhance", enhance_node)
    builder.add_node("assess", assess_node)
    builder.add_node("route", route_node)
    builder.add_node("extract", extract_node)
    builder.add_node("output", output_node)

    builder.add_edge(START, "convert")
    builder.add_conditional_edges(
        "convert", _after_convert, {"enhance": "enhance", "output": "output"}
    )
    builder.add_edge("enhance", "assess")
    builder.add_edge("assess", "route")
    builder.add_edge("route", "extract")
    builder.add_conditional_edges(
        "extract", _after_extract, {"enhance": "enhance", "output": "output"}
    )
    builder.add_edge("output", END)
    return builder


def _finalize(output_json: str, ctx: DocumentContext) -> None:
    """Adds the overall document latency report and the token/retry summary
    to result.json, and stores the total processing time in every page's
    metadata."""
    path = Path(output_json)
    record = json.loads(path.read_text(encoding="utf-8"))
    total = ctx.latency.total()
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


def _report_latency(ctx: DocumentContext) -> None:
    """Prints the processing time of every node and the document total."""
    totals = ctx.latency.node_totals()
    breakdown = "; ".join(
        f"{node} {seconds:.2f}s" for node, seconds in totals.items()
    )
    console.emit(
        ctx.document_id,
        "summary",
        "COMPLETED",
        f"node times: {breakdown}",
        ctx.latency.total(),
    )


async def run_async(pdf_files: list[Path] | None = None) -> int:
    """Runs the graph once per PDF (or for the given files) concurrently:
    up to MAX_CONCURRENT_DOCUMENTS documents at a time, each document page by
    page, results reported in the order documents finish. Returns a shell
    exit code, so both main.py and the web UI share the exact same pipeline."""
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

    graph = build_graph().compile()
    semaphore = asyncio.Semaphore(max(1, config.MAX_CONCURRENT_DOCUMENTS))

    async def process_one(pdf_path: Path) -> bool:
        """Processes one document and reports its result the moment it is
        done - documents finish independently and out of order."""
        ctx = DocumentContext.create(pdf_path)
        async with semaphore:
            console.emit(ctx.document_id, "document", "STARTED", pdf_path.name)
            try:
                state = await graph.ainvoke(
                    {"ctx": ctx, "page_index": 0, "page_records": []}
                )
            except Exception as exc:
                logger.exception("Pipeline crashed for %s", ctx.document_id)
                console.emit(ctx.document_id, "document", "FAILED", str(exc))
                return False
        if state.get("error"):
            console.emit(ctx.document_id, "document", "FAILED", state["error"])
            return False
        output_json = state.get("output_json", "")
        if output_json:
            _finalize(output_json, ctx)
        _report_latency(ctx)
        console.emit(ctx.document_id, "result", "SAVED", output_json)
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
    """Synchronous entry point for main.py and the web UI: runs the
    asynchronous pipeline to completion and returns its exit code."""
    return asyncio.run(run_async(pdf_files))
