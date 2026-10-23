"""
pipeline_graph.py — the whole document pipeline, explained LINE BY LINE.
(Annotated learning copy of src/pipeline_graph.py — the real source is untouched.)

THE MAP (who calls whom):

    run() -> run_async()                     STEP 9 + 10   entry point + orchestration
        DocumentContext.create()             STEP 2        tools, IDs, budgets
        document graph : convert -> pages -> output         STEP 3 -> 8 -> 8
        page graph (per page): enhance -> assess -> route -> extract   STEP 4 -> 5 -> 6 -> 7

DATA FLOW RULE: every node RETURNS a small dict; LangGraph merges it into the
state (DocumentState for the document graph, PageState for the page graph).
The toolkit ctx (DocumentContext) travels INSIDE the state, so every node can
reach the IDs, budgets and latency tracker.

FILE ORDER == THE 10 STEPS:
    1  docstring + constants                (this section)
    2  tools, mailboxes, graph wiring       (_build_gates ... build_document_graph)
    3  convert_node     PDF -> page images
    4  enhance_node     clean the image
    5  assess_node      score 0-100 + tier
    6  route_node       tier -> model
    7  extract_node     LLM call -> fields
    8  pages_node + output_node             fan out all pages + write output folder
    9  run_async start  input folder -> document list
    10 process_one/run  orchestrate + totals + exit code
"""

# Here, we enable modern type hints (e.g. "int | None") in Python 3.9+.
from __future__ import annotations

# Here, we import asyncio — Task 2: all LLM/network work is asynchronous.
import asyncio
# Here, we import json to write result.json at the end.
import json
# Here, we import logging so errors are printed without crashing the run.
import logging
# Here, we import dataclass (the DocumentContext kit) and field (default values).
from dataclasses import dataclass, field
# Here, we import Path so we can work with file/folder paths.
from pathlib import Path
# Here, we import TypedDict — the "mailbox" states DocumentState / PageState.
from typing import TypedDict

# Here, we import the LangGraph building blocks: END, START and StateGraph.
from langgraph.graph import END, START, StateGraph

# Here, we import our config (.env settings) and the console line printer.
from src import config, console
# Here, we import the two budgets (Task 5: retries, Task 6: tokens).
from src.budget import RetryBudget, TokenBudget
# Here, we import the Feature 1 engine: PDF -> images.
from src.conversion import ImageConversionLayer
# Here, we import the Feature 5 engine: LLM data extraction.
from src.extraction import ExtractionEngine
# Here, we import the ID helpers (Task 1: document and page IDs).
from src.identity import allocate_document_id, page_id_for
# Here, we import the latency tracker (Task 3 + Task 4).
from src.latency import LatencyTracker
# Here, we import the Feature 2 engine: image enhancement.
from src.preprocessing import ImagePreprocessingEngine
# Here, we import the Feature 3 types + engine: quality assessment.
from src.quality import QualityAssessment, QualityAssessmentEngine
# Here, we import the Feature 4 router + its decision type.
from src.router import ModelRouter, RoutingDecision

# Here, we create the "pipeline" logger (used when a page or document crashes).
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# STEP 1 — CONSTANTS: the names of the 6 features and the shared texts.
# ---------------------------------------------------------------------------

# Here, we map every node name to its human-readable feature title.
FEATURES = {
    # Here, Feature 1 — PDF to images (runs once per document).
    "convert": "PDF-to-Images converter",
    # Here, Feature 2 — image cleanup (runs once per page).
    "enhance": "Image enhancement",
    # Here, Feature 3 — quality score (runs once per page).
    "assess": "Quality assessment of images",
    # Here, Feature 4 — pick the model (runs once per page).
    "route": "Model router based on the quality score",
    # Here, Feature 5 — the LLM call (runs once per page).
    "extract": "Data extraction",
    # Here, Feature 6 — write the output folder (runs once per document).
    "output": "JSON output",
}

# Here, we define the message shown when a document runs out of tokens (Task 6).
TOKEN_LIMIT_MESSAGE = (
    "Token limit has been reached for this document. "
    "Further model calls have been stopped."
)

# Here, we define the "zero tokens" block used by pages that never called a model.
ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


# ===========================================================================
# STEP 2 — THE TOOLKIT AND THE MAILBOXES
#   _build_gates / _start / _done / _report_token_limit / _blank_record
#   DocumentContext (the kit) + PageState / DocumentState (the mailboxes)
#   build_page_graph / build_document_graph (the wiring)
# ===========================================================================

def _build_gates() -> dict[str, asyncio.Semaphore]:
    """One semaphore per feature FOR ONE DOCUMENT, so the configured
    per-feature page concurrency is a per-document limit."""
    # Here, we build one semaphore per feature node (enhance/assess/route/extract).
    return {
        # Here, max(1, limit) protects us from a bad .env value of 0.
        node: asyncio.Semaphore(max(1, limit))
        # Here, we read the limits: enhance 5, assess 3, route 2, extract 4.
        for node, limit in config.FEATURE_CONCURRENCY.items()
    }


def _start(subject: str, node: str) -> None:
    """Prints the STARTED line — the demo's only progress display."""
    # Here, we print e.g. "0010/01 | enhance | STARTED | Image enhancement".
    console.emit(subject, node, "STARTED", FEATURES[node])


def _done(subject: str, node: str, timing, detail: str = "") -> None:
    """Prints one node's finished line: status, latency vs threshold, result."""
    # Here, we print the finished line for one node run (Task 3 report).
    console.emit(
        # Here, "subject" is the document ID ("0010") or page ID ("0010/01").
        subject,
        # Here, "node" is the feature name (convert/enhance/.../output).
        node,
        # Here, the status is "OK" or "OVER-THRESHOLD" (from the latency tracker).
        timing.status,
        # Here, the detail text is what the node produced (or its error).
        detail or FEATURES[node],
        # Here, the measured seconds of this node run.
        timing.seconds,
        # Here, the configured threshold so the reader can compare.
        timing.threshold,
    )


def _report_token_limit(ctx: DocumentContext) -> None:
    """Announces ONCE that the document's token budget is exhausted."""
    # Here, we make sure the message is printed only once per document.
    if not ctx.token_limit_reported:
        # Here, we flip the flag so later pages stay quiet.
        ctx.token_limit_reported = True
        # Here, we print the "Token limit reached" line (Task 6).
        console.emit(ctx.document_id, "tokens", "STOPPED", TOKEN_LIMIT_MESSAGE)


def _blank_record(ctx: DocumentContext, page_number: int, page_id: str) -> dict:
    """The metadata skeleton every page record starts from."""
    # Here, we build the empty page record used when a page was skipped/failed.
    return {
        # Here, the 1-based page number (1, 2, 3, ...).
        "page": page_number,
        # Here, the page ID from Task 1, e.g. "0010/01".
        "page_id": page_id,
        # Here, no image name yet (filled only when a page really ran).
        "image": None,
        # Here, "stopped" = the page never ran (e.g. token limit).
        "status": "stopped",
        # Here, no quality score/tier because the page never reached assess.
        "quality_score": None,
        "quality_tier": None,
        # Here, no model because no model call happened.
        "model": None,
        # Here, empty extraction results.
        "extracted_fields": {},
        "field_confidence_scores": {},
        # Here, success stays False.
        "success": False,
        # Here, the caller fills in the reason (e.g. TOKEN_LIMIT_MESSAGE).
        "error": None,
        # Here, Task 4: the time spent on this page so far (usually 0).
        "processing_time": ctx.latency.subject_total(page_id),
        # Here, Task 6: zero tokens because no model call was made.
        "token_usage": dict(ZERO_USAGE),
        # Here, Task 6: the document's running token total.
        "document_total_tokens": ctx.token_budget.used,
        # Here, Task 5: zero retries because no API call was made.
        "retries_used": 0,
    }


@dataclass
class DocumentContext:
    """Everything one document's run needs — the TOOLKIT (not data!).
    Data travels in DocumentState / PageState; tools travel in here."""

    # Here, the input PDF this document is.
    pdf_path: Path
    # Here, Task 1: the unique document ID, e.g. "0010".
    document_id: str
    # Here, the Feature 1 engine (PDF -> images).
    conversion: ImageConversionLayer
    # Here, the Feature 2 engine (image cleanup).
    preprocessing: ImagePreprocessingEngine
    # Here, the Feature 3 engine (quality score).
    quality: QualityAssessmentEngine
    # Here, the Feature 4 engine (tier -> model).
    router: ModelRouter
    # Here, the Feature 5 engine (LLM extraction).
    extractor: ExtractionEngine
    # Here, Task 6: the token budget shared by every model call of this document.
    token_budget: TokenBudget
    # Here, Task 5: the retry budget shared by every model call of this document.
    retry_budget: RetryBudget
    # Here, Task 3 + Task 4: the latency tracker of this document.
    latency: LatencyTracker
    # Here, the per-feature concurrency gates of THIS document.
    gates: dict[str, asyncio.Semaphore]
    # Here, the compiled page graph (enhance -> assess -> route -> extract).
    page_graph: object
    # Here, the page IDs ["0010/01", "0010/02", ...] filled by convert_node.
    page_ids: list[str] = field(default_factory=list)
    # Here, the page count filled by convert_node.
    page_count: int = 0
    # Here, whether the "token limit reached" message was already printed.
    token_limit_reported: bool = False

    @classmethod
    def create(cls, pdf_path: Path) -> DocumentContext:
        """Builds a fully configured toolkit for ONE document."""
        # Here, we build the complete kit in one place (called by process_one).
        return cls(
            # Here, we remember which PDF this is.
            pdf_path=pdf_path,
            # Here, Task 1: we allocate the unique document ID BEFORE processing,
            # so it stays stable even when documents finish out of order.
            document_id=allocate_document_id(),
            # Here, we create the Feature 1 converter at the configured DPI.
            conversion=ImageConversionLayer(dpi=config.DPI),
            # Here, we create the Feature 2 enhancer (all steps on).
            preprocessing=ImagePreprocessingEngine(),
            # Here, we create the Feature 3 quality engine (Tesseract OCR).
            quality=QualityAssessmentEngine(),
            # Here, we create the Feature 4 router (.env tier -> model table).
            router=ModelRouter(),
            # Here, we create the Feature 5 extractor (locked to template fields).
            extractor=ExtractionEngine(),
            # Here, Task 6: one token budget for the whole document (e.g. 5000).
            token_budget=TokenBudget(config.DOCUMENT_TOKEN_LIMIT),
            # Here, Task 5: e.g. 2 retries per page AND 5 per document.
            retry_budget=RetryBudget(
                config.LLM_PAGE_RETRY_LIMIT, config.LLM_DOCUMENT_RETRY_LIMIT
            ),
            # Here, Task 3: the tracker with every node's latency threshold.
            latency=LatencyTracker(config.LATENCY_THRESHOLDS),
            # Here, we build this document's own concurrency gates.
            gates=_build_gates(),
            # Here, we compile the page graph once so every page can reuse it.
            page_graph=build_page_graph().compile(),
        )


class PageState(TypedDict, total=False):
    """The MAILBOX of the page graph — data handed from page node to page node."""

    # Here, the toolkit (shared with all pages of the same document).
    ctx: DocumentContext
    # Here, the page number (1-based).
    page_number: int
    # Here, Task 1: the page ID, e.g. "0010/01".
    page_id: str
    # Here, the raw converted image (arrives from convert_node via pages_node).
    image: object
    # Here, the cleaned image — written by enhance_node (STEP 4).
    enhanced_image: object
    # Here, the score + tier — written by assess_node (STEP 5).
    assessment: dict
    # Here, the model decision — written by route_node (STEP 6).
    routing: dict
    # Here, the final page record — written by extract_node (STEP 7).
    record: dict


class DocumentState(TypedDict, total=False):
    """The MAILBOX of the document graph — data handed between the 3 document nodes."""

    # Here, the toolkit (put in by process_one when the graph starts).
    ctx: DocumentContext
    # Here, all converted page images — written by convert_node (STEP 3).
    images: list
    # Here, all (record, image) pairs — written by pages_node (STEP 8).
    page_results: list
    # Here, the path of result.json — written by output_node (STEP 8).
    output_json: str
    # Here, the error text if conversion failed — written by convert_node.
    error: str | None


# ===========================================================================
# STEP 3 — CONVERT (Feature 1, document level): PDF -> page images
# ===========================================================================

async def convert_node(state: DocumentState) -> dict:
    """Feature 1 — turns the PDF into page images ONCE per document."""
    # Here, we take the toolkit out of the document mailbox.
    ctx = state["ctx"]
    # Here, we print: "<doc id> | convert | STARTED | PDF-to-Images converter".
    _start(ctx.document_id, "convert")
    # Here, Task 3/4: we start measuring this node's latency.
    with ctx.latency.measure("convert", ctx.document_id) as timing:
        # Here, we run the CPU-heavy conversion in a worker thread so the
        # asyncio event loop stays free for other documents (Task 2).
        converted = await asyncio.to_thread(
            # Here, the real work: pdf2image renders every page at 300 DPI.
            ctx.conversion.convert_pages, ctx.pdf_path
        )
    # Here, we check the result: a broken PDF must NOT crash the run.
    if not converted.success:
        # Here, we read the error text (e.g. "Poppler missing" / "invalid PDF").
        message = converted.error or "conversion failed"
        # Here, we print the failed line for this document.
        _done(ctx.document_id, "convert", timing, f"failed; {message}")
        # Here, we put the error into the mailbox; run_async reports FAILED.
        return {"error": message}
    # Here, we also treat a PDF with zero pages as a failure.
    if converted.page_count == 0:
        # Here, we build the message for the empty case.
        message = "document has no pages"
        # Here, we print the failed line.
        _done(ctx.document_id, "convert", timing, f"failed; {message}")
        # Here, we put the error into the mailbox.
        return {"error": message}
    # Here, we remember HOW MANY pages this document has (used by pages_node).
    ctx.page_count = converted.page_count
    # Here, Task 1: we build one page ID per page — "0010/01", "0010/02", ...
    ctx.page_ids = [
        # Here, page_id_for("0010", 2) -> "0010/02".
        page_id_for(ctx.document_id, number)
        # Here, the range is 1..page_count because page numbers are 1-based.
        for number in range(1, converted.page_count + 1)
    ]
    # Here, we print the OK line: status, latency and "N pages".
    _done(
        ctx.document_id,
        "convert",
        timing,
        f"{FEATURES['convert']}; {converted.page_count} "
        f"page{'s' if converted.page_count != 1 else ''}",
    )
    # Here, we hand the page images to the next node (pages_node) via the mailbox.
    return {"images": converted.pages}


# ===========================================================================
# STEP 4 — ENHANCE (Feature 2, page level): clean the page image
# ===========================================================================

async def enhance_node(state: PageState) -> dict:
    """Feature 2 — cleans up one page image so OCR and the vision model can
    read it clearly. First node of the page graph (page level)."""
    # Here, we take the toolkit out of the page mailbox.
    ctx = state["ctx"]
    # Here, we take this page's ID, e.g. "0010/01" (Task 1).
    page_id = state["page_id"]
    # Here, we enter this document's enhance gate: at most 5 pages at once.
    async with ctx.gates["enhance"]:
        # Here, we print: "<page id> | enhance | STARTED | Image enhancement".
        _start(page_id, "enhance")
        # Here, Task 3/4: start measuring this page's enhance latency.
        with ctx.latency.measure("enhance", page_id) as timing:
            # Here, we run the OpenCV chain (grayscale, deblur, denoise,
            # deskew, contrast) in a worker thread (Task 2: loop stays free).
            image = await asyncio.to_thread(
                # Here, the raw converted image goes IN to the engine.
                ctx.preprocessing.enhance, state["image"]
            )
        # Here, we print the finished line with the latency.
        _done(page_id, "enhance", timing)
        # Here, we put the clean image into the mailbox for assess_node (STEP 5).
        return {"enhanced_image": image}


# ===========================================================================
# STEP 5 — ASSESS (Feature 3, page level): score 0-100 + quality tier
# ===========================================================================

async def assess_node(state: PageState) -> dict:
    """Feature 3 — scores the page 0-100 and assigns clear/blurry/very_blurry."""
    # Here, we take the toolkit out of the page mailbox.
    ctx = state["ctx"]
    # Here, we take the page ID (Task 1).
    page_id = state["page_id"]
    # Here, we enter the assess gate: at most 3 pages at once.
    async with ctx.gates["assess"]:
        # Here, we print: "<page id> | assess | STARTED | Quality assessment...".
        _start(page_id, "assess")
        # Here, Task 3/4: start measuring this page's assess latency.
        with ctx.latency.measure("assess", page_id) as timing:
            # Here, the Tesseract OCR confidence scoring runs in a worker thread.
            result = await asyncio.to_thread(
                # Here, the CLEAN image (from STEP 4) goes in; score+tier come out.
                ctx.quality.assess, state["enhanced_image"]
            )
        # Here, we print e.g. "score 83.0 -> clear" (explains later routing!).
        _done(page_id, "assess", timing, f"score {result.score} -> {result.tier}")
        # Here, we put the assessment into the mailbox for route_node (STEP 6).
        return {
            "assessment": {
                # Here, we keep the page ID with the result (Task 1).
                "page_id": page_id,
                # Here, the 0-100 score (e.g. 83.0).
                "score": result.score,
                # Here, the tier: clear / blurry / very_blurry.
                "tier": result.tier,
            }
        }


# ===========================================================================
# STEP 6 — ROUTE (Feature 4, page level): quality tier -> extraction model
# ===========================================================================

async def route_node(state: PageState) -> dict:
    """Feature 4 — maps the tier to a model: clear pages use the cheap model,
    only hard pages pay for the strong one. A local decision, no API call."""
    # Here, we take the toolkit out of the page mailbox.
    ctx = state["ctx"]
    # Here, we take the assessment produced by assess_node (STEP 5).
    assessment = state["assessment"]
    # Here, we take the page ID (Task 1) — the routing key, never the file name.
    page_id = state["page_id"]
    # Here, we enter the route gate: at most 2 pages at once.
    async with ctx.gates["route"]:
        # Here, we print: "<page id> | route | STARTED | Model router...".
        _start(page_id, "route")
        # Here, Task 3/4: start measuring this tiny (local) node.
        with ctx.latency.measure("route", page_id) as timing:
            # Here, the router lookup runs in a thread (pure dict lookup).
            decision = await asyncio.to_thread(
                # Here, we call the router with a QualityAssessment value object.
                ctx.router.route,
                QualityAssessment(
                    # Here, we rebuild the value object from the mailbox dict.
                    score=assessment["score"], tier=assessment["tier"]
                ),
            )
        # Here, we print e.g. "model qwen/qwen3.7-plus:free".
        _done(page_id, "route", timing, f"model {decision.model}")
        # Here, we put the routing decision into the mailbox for extract_node.
        return {
            "routing": {
                # Here, Task 1: the page ID again, so the decision is traceable.
                "page_id": page_id,
                # Here, the chosen model name.
                "model": decision.model,
                # Here, the tier that led to the choice.
                "tier": decision.tier,
                # Here, the score that led to the choice.
                "score": decision.score,
            }
        }


# ===========================================================================
# STEP 7 — EXTRACT (Feature 5, page level): THE LLM CALL -> fields
# ===========================================================================

async def extract_node(state: PageState) -> dict:
    """Feature 5 — the only model call in the pipeline. Turns the page image
    into fields + confidence scores. Task 5 (retries) and Task 6 (tokens)
    are enforced here."""
    # Here, we take the toolkit out of the page mailbox.
    ctx = state["ctx"]
    # Here, we take the page ID (Task 1).
    page_id = state["page_id"]
    # Here, we take the routing decision from route_node (STEP 6).
    routing = state["routing"]
    # Here, we rebuild the RoutingDecision value object for the extractor.
    decision = RoutingDecision(
        # Here, the model that will be called.
        model=routing["model"],
        # Here, the tier that selected it.
        tier=routing["tier"],
        # Here, the score that selected it.
        score=routing["score"],
    )

    # Here, we enter the extract gate: at most 4 pages at once.
    async with ctx.gates["extract"]:
        # Here, Task 6: if the document's token budget is gone, we call NO model.
        if ctx.token_budget.exhausted:
            # Here, we print the "Token limit reached" line (once).
            _report_token_limit(ctx)
            # Here, we build the empty record for this skipped page.
            record = _blank_record(ctx, state["page_number"], page_id)
            # Here, we explain WHY the page was skipped.
            record["error"] = TOKEN_LIMIT_MESSAGE
            # Here, we still keep the score/tier the page earned before the stop.
            record["quality_score"] = routing["score"]
            record["quality_tier"] = routing["tier"]
            # Here, we return the skip record into the mailbox — no model call!
            return {"record": record}
        # Here, we print: "<page id> | extract | STARTED | Data extraction".
        _start(page_id, "extract")
        # Here, Task 3/4: measure the slowest node (the network wait).
        with ctx.latency.measure("extract", page_id) as timing:
            # Here, the actual async LLM call (Task 2): image + prompt -> JSON.
            result = await ctx.extractor.extract(
                # Here, the clean image (from STEP 4) is what the model sees.
                state["enhanced_image"],
                # Here, the model choice (from STEP 6).
                decision,
                # Here, Task 5: the shared retry budget limits failures.
                retry_budget=ctx.retry_budget,
                # Here, Task 1: retries are logged under this page ID.
                subject=page_id,
            )
        # Here, Task 6: add this call's tokens to the document's running total.
        usage = ctx.token_budget.record(result.input_tokens, result.output_tokens)

        # Here, we decide the page status from the extraction result.
        status = "completed" if result.success else "failed"
        # Here, we start building the detail text of the console line.
        detail = [
            # Here, "completed" or "failed".
            status,
            # Here, e.g. "tokens 3358 (input 3084, output 274)".
            f"tokens {usage.total_tokens} (input {usage.input_tokens}, output {usage.output_tokens})",
            # Here, e.g. "document total 3358 tokens" (Task 6 running total).
            f"document total {ctx.token_budget.used} tokens",
        ]
        # Here, if it failed, we insert the error text into the line.
        if result.error:
            detail.insert(1, result.error)
        # Here, Task 5: if retries happened, we show how many were used.
        if result.retries_used:
            detail.append(f"retries {result.retries_used}")
        # Here, we print the finished extract line.
        _done(page_id, "extract", timing, "; ".join(detail))

    # Here, we take the assessment again (it left the "extract" gate scope).
    assessment = state["assessment"]
    # Here, we build THE PAGE RECORD — this is the data that ends up in result.json.
    record = {
        # Here, the page number (1-based).
        "page": state["page_number"],
        # Here, Task 1: the page ID stored in the metadata.
        "page_id": page_id,
        # Here, the image file name that output_node will save ("page-01.png").
        "image": f"page-{state['page_number']:02d}.{config.IMAGE_FORMAT}",
        # Here, "completed" or "failed".
        "status": status,
        # Here, the quality score from STEP 5.
        "quality_score": assessment["score"],
        # Here, the quality tier from STEP 5.
        "quality_tier": assessment["tier"],
        # Here, the model actually used (from STEP 6 / the extractor).
        "model": result.model,
        # Here, the extracted fields, e.g. {"document_no": "W162647", ...}.
        "extracted_fields": result.fields,
        # Here, the per-field confidence scores, e.g. {"document_no": 89, ...}.
        "field_confidence_scores": result.confidence_scores,
        # Here, True only when the model call succeeded.
        "success": result.success,
        # Here, the error text if any (None when fine).
        "error": result.error,
        # Here, Task 4: total time of this page (enhance+assess+route+extract).
        "processing_time": ctx.latency.subject_total(page_id),
        # Here, Task 6: this page's model token usage.
        "token_usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
        # Here, Task 6: the document's token total AFTER this page.
        "document_total_tokens": ctx.token_budget.used,
        # Here, Task 5: how many retries this page needed.
        "retries_used": result.retries_used,
    }

    # Here, Task 6: if this call just exhausted the budget, we announce it now.
    if ctx.token_budget.exhausted:
        _report_token_limit(ctx)
    # Here, we put the finished record into the mailbox (pages_node picks it up).
    return {"record": record}


# ===========================================================================
# STEP 8 — PAGES + OUTPUT (document level): fan out all pages, write the folder
# ===========================================================================

async def pages_node(state: DocumentState) -> dict:
    """Runs EVERY page through the page graph (STEPS 4-7) at the same time,
    bounded only by the per-feature gates. Collects the results."""
    # Here, we take the toolkit out of the document mailbox.
    ctx = state["ctx"]
    # Here, we take the converted page images from convert_node (STEP 3).
    images = state["images"]

    async def process_page(number: int) -> tuple[dict, object]:
        """Runs ONE already-rendered page through the page graph."""
        # Here, Task 1: we look up this page's ID, e.g. "0010/02".
        page_id = ctx.page_ids[number - 1]
        # Here, Task 6: a page whose document is out of tokens never starts.
        if ctx.token_budget.exhausted:
            # Here, we print the token-limit message (once per document).
            _report_token_limit(ctx)
            # Here, we build the empty "stopped" record for this page.
            record = _blank_record(ctx, number, page_id)
            # Here, we explain why the page did not run.
            record["error"] = TOKEN_LIMIT_MESSAGE
            # Here, we return (record, no image) to the collector below.
            return record, None
        try:
            # Here, we RUN THE PAGE GRAPH (enhance->assess->route->extract).
            page_state = await ctx.page_graph.ainvoke(
                {
                    # Here, we pass the toolkit into the page mailbox.
                    "ctx": ctx,
                    # Here, the page number (1-based).
                    "page_number": number,
                    # Here, Task 1: the page ID.
                    "page_id": page_id,
                    # Here, the converted image for THIS page.
                    "image": images[number - 1],
                }
            )
        except Exception as exc:
            # Here, a crashed page is logged, never fatal to the document.
            logger.exception("Pipeline crashed for %s", page_id)
            # Here, we build the failed record.
            record = _blank_record(ctx, number, page_id)
            record["status"] = "failed"
            # Here, we keep the exception text as the error.
            record["error"] = str(exc)
            # Here, we return (failed record, no image).
            return record, None
        # Here, the happy path: the page graph produced a record.
        if page_state.get("record"):
            # Here, we ALSO return the enhanced image so output_node can save it.
            return page_state["record"], page_state.get("enhanced_image")
        # Here, the page graph ended without a record (unexpected) -> failed.
        record = _blank_record(ctx, number, page_id)
        record["status"] = "failed"
        record["error"] = "page processing failed"
        # Here, we return the fallback failed record.
        return record, None

    # Here, TASK 2 CONCURRENCY: start ALL pages at once and wait for all.
    results = await asyncio.gather(
        # Here, one process_page task per page (1..page_count).
        *(process_page(number) for number in range(1, len(images) + 1))
    )
    # Here, we hand every (record, image) pair to output_node via the mailbox.
    return {"page_results": list(results)}


def output_node(state: DocumentState) -> dict:
    """Feature 6 (document level) — writes the enhanced images and result.json
    when every page of the document is done."""
    # Here, we take the toolkit out of the document mailbox.
    ctx = state["ctx"]
    # Here, we take the collected (record, image) pairs from pages_node.
    results = state["page_results"]
    # Here, we sort the records by page number (gather keeps order, but be safe).
    pages = sorted((record for record, _ in results), key=lambda r: r["page"])
    # Here, we map page number -> enhanced image (only pages that produced one).
    images = {
        record["page"]: image
        for record, image in results
        if image is not None
    }
    # Here, we write the files and put the result.json path into the mailbox.
    return {"output_json": _write_output(ctx, pages, images) or ""}


def _write_output(
    ctx: DocumentContext, pages: list[dict], images: dict[int, object]
) -> str | None:
    """Feature 6 — writes page-XX.png images + result.json into
    data/output/<pdf name>/. Nothing is written when nothing was processed."""
    # Here, zero processed pages means there is nothing to write.
    if not pages:
        return None
    # Here, we build e.g. data/output/BRIGHT PHARMACY-5/.
    directory = config.OUTPUT_DIR / ctx.pdf_path.stem
    # Here, we create the folder (and parents) if it does not exist yet.
    directory.mkdir(parents=True, exist_ok=True)

    # Here, we print: "<doc id> | output | STARTED | JSON output".
    _start(ctx.document_id, "output")
    # Here, Task 3/4: measure the output node of this document.
    with ctx.latency.measure("output", ctx.document_id) as timing:
        # Here, we walk the sorted page records.
        for record in pages:
            # Here, we look up this page's enhanced image.
            image = images.get(record["page"])
            # Here, we save it, e.g. page-01.png (skip pages without an image).
            if image is not None and record["image"]:
                image.save(directory / record["image"])
        # Here, we build the path of the final JSON file.
        output_json = directory / "result.json"
        # Here, we write result.json: document name + ID + all page records.
        output_json.write_text(
            json.dumps(
                {
                    # Here, the source file name, e.g. "BRIGHT PHARMACY-5.pdf".
                    "document": ctx.pdf_path.name,
                    # Here, Task 1: the document ID stored in the metadata.
                    "document_id": ctx.document_id,
                    # Here, every page record (fields, score, model, tokens...).
                    "pages": pages,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    # Here, we print the OK line with "N pages; result.json".
    _done(
        ctx.document_id,
        "output",
        timing,
        f"{FEATURES['output']}; {len(pages)} "
        f"page{'s' if len(pages) != 1 else ''}; result.json",
    )
    # Here, we return the file path (goes into DocumentState["output_json"]).
    return str(output_json)


# ===========================================================================
# STEP 2 (continued) — THE WIRING: the two LangGraph graphs
# ===========================================================================

def build_page_graph() -> StateGraph:
    """Wires the four PAGE nodes: enhance -> assess -> route -> extract.
    Compiled once in DocumentContext.create, invoked per page by pages_node."""
    # Here, we start a graph whose mailbox type is PageState.
    builder = StateGraph(PageState)
    # Here, we register STEP 4 (this is WIRING — it does not run yet).
    builder.add_node("enhance", enhance_node)
    # Here, we register STEP 5.
    builder.add_node("assess", assess_node)
    # Here, we register STEP 6.
    builder.add_node("route", route_node)
    # Here, we register STEP 7.
    builder.add_node("extract", extract_node)

    # Here, we wire the order: START -> enhance.
    builder.add_edge(START, "enhance")
    # Here, enhance -> assess.
    builder.add_edge("enhance", "assess")
    # Here, assess -> route.
    builder.add_edge("assess", "route")
    # Here, route -> extract.
    builder.add_edge("route", "extract")
    # Here, extract -> END (the page's record is now in the mailbox).
    builder.add_edge("extract", END)
    # Here, we hand the un-compiled builder back (the caller compiles it).
    return builder


def build_document_graph() -> StateGraph:
    """Wires the three DOCUMENT nodes: convert -> pages -> output."""
    # Here, we start a graph whose mailbox type is DocumentState.
    builder = StateGraph(DocumentState)
    # Here, we register STEP 3 (wiring only).
    builder.add_node("convert", convert_node)
    # Here, we register STEP 8 part 1 (fan out all pages).
    builder.add_node("pages", pages_node)
    # Here, we register STEP 8 part 2 (write the output folder).
    builder.add_node("output", output_node)
    # Here, we wire: START -> convert.
    builder.add_edge(START, "convert")
    # Here, convert -> pages (the images are now in DocumentState).
    builder.add_edge("convert", "pages")
    # Here, pages -> output (the page_results are now in DocumentState).
    builder.add_edge("pages", "output")
    # Here, output -> END (result.json is written).
    builder.add_edge("output", END)
    # Here, we return the builder to the caller (run_async compiles it).
    return builder


# ===========================================================================
# STEP 10 (part) — FINALIZE + LATENCY REPORT (after the graph finished)
# ===========================================================================

def _finalize(output_json: str, ctx: DocumentContext) -> None:
    """Adds the run-wide telemetry to result.json: Task 4 totals plus the
    Task 5 (retries) and Task 6 (tokens) summaries, and stamps the total
    processing time on every page record."""
    # Here, we build a Path object for the result.json written by output_node.
    path = Path(output_json)
    # Here, we read the JSON back so we can add the final numbers.
    record = json.loads(path.read_text(encoding="utf-8"))
    # Here, Task 4: the total processing time of the whole document.
    total = ctx.latency.total()
    # Here, Task 4: store the document total at the top level.
    record["total_processing_time"] = total
    # Here, Task 4: store the per-node breakdown (convert/enhance/... seconds).
    record["node_latency"] = ctx.latency.node_totals()
    # Here, Task 6: store the token summary of the document.
    record["token_usage"] = {
        # Here, the configured document limit (e.g. 5000).
        "limit": ctx.token_budget.limit,
        # Here, what the document really used (e.g. 3358).
        "used": ctx.token_budget.used,
        # Here, whether the limit stopped further model calls.
        "limit_reached": ctx.token_budget.exhausted,
    }
    # Here, Task 5: store the retry summary of the document.
    record["retry_usage"] = {
        # Here, the per-page retry limit (e.g. 2).
        "page_limit": ctx.retry_budget.page_limit,
        # Here, the per-document retry limit (e.g. 5).
        "document_limit": ctx.retry_budget.document_limit,
        # Here, how many retries were really used (e.g. 0).
        "retries_used": ctx.retry_budget.retries_used,
    }
    # Here, Task 4: every page also learns the document's total time.
    for page in record["pages"]:
        page["total_processing_time"] = total
    # Here, we write the enriched result.json back to disk.
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _report_latency(ctx: DocumentContext) -> None:
    """Prints the Task 4 report: the processing time of every node plus the
    document total — one console line."""
    # Here, we collect e.g. {"convert": 8.61, "enhance": 35.6, ...}.
    totals = ctx.latency.node_totals()
    # Here, we turn the numbers into one readable text.
    breakdown = "; ".join(
        f"{node} {seconds:.2f}s" for node, seconds in totals.items()
    )
    # Here, we print the "summary | COMPLETED" line with the document total.
    console.emit(
        ctx.document_id,
        "summary",
        "COMPLETED",
        f"node times: {breakdown}",
        ctx.latency.total(),
    )


# ===========================================================================
# STEP 9 + 10 — THE ENTRY POINT AND THE ORCHESTRATION
# ===========================================================================

async def run_async(pdf_files: list[Path] | None = None) -> int:
    """STEP 9: the starting point — takes the documents (argument, or every
    PDF in the input folder). STEP 10: runs each document through the
    document graph concurrently and reports the result. Returns an exit code
    so main.py AND the web UI share this exact pipeline."""
    # Here, we install the aligned console log format ("TIME | SUBJECT | ...").
    console.install()
    # Here, we make sure the input folder exists.
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Here, we make sure the output folder exists (also holds the ID counter).
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Here, STEP 9: no arguments means "take every PDF in the input folder".
    if pdf_files is None:
        pdf_files = sorted(
            # Here, we scan the folder and keep only real files.
            path
            for path in config.INPUT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
    # Here, an empty folder is a valid, quiet run.
    if not pdf_files:
        # Here, we tell the user no PDFs were found.
        console.emit(
            "run", "summary", "EMPTY", f"No PDF documents found in '{config.INPUT_DIR}'."
        )
        # Here, exit code 0 — nothing failed.
        return 0

    # Here, STEP 2: we compile the document graph ONCE, shared by all documents.
    graph = build_document_graph().compile()
    # Here, we cap how many documents run at the same time (e.g. 4).
    document_semaphore = asyncio.Semaphore(
        max(1, config.MAX_CONCURRENT_DOCUMENTS)
    )

    async def process_one(pdf_path: Path) -> bool:
        """STEP 10: processes ONE document and reports the moment it is done
        (documents finish independently and out of order)."""
        # Here, we build the toolkit: document ID, engines, budgets (STEP 2).
        ctx = DocumentContext.create(pdf_path)
        # Here, we wait for a free document slot (max N documents at once).
        async with document_semaphore:
            # Here, we print "<doc id> | document | STARTED | <file name>".
            console.emit(ctx.document_id, "document", "STARTED", pdf_path.name)
            try:
                # Here, THE RUN: convert -> pages -> output for this document.
                state = await graph.ainvoke({"ctx": ctx})
            except Exception as exc:
                # Here, a crashed document is logged and reported, never fatal.
                logger.exception("Pipeline crashed for %s", ctx.document_id)
                # Here, we print the FAILED line.
                console.emit(ctx.document_id, "document", "FAILED", str(exc))
                # Here, False = this document counts as failed (exit code 1).
                return False
        # Here, convert_node puts errors into state["error"] instead of raising.
        if state.get("error"):
            # Here, we print the FAILED line with that error.
            console.emit(ctx.document_id, "document", "FAILED", state["error"])
            # Here, count the document as failed.
            return False
        # Here, we read the result.json path from the final mailbox ("" if none).
        output_json = state.get("output_json", "")
        # Here, only enrich the file if the file really exists.
        if output_json:
            # Here, Task 4/5/6: add totals + token/retry summaries to result.json.
            _finalize(output_json, ctx)
        # Here, Task 4: print the "node times: ..." summary line.
        _report_latency(ctx)
        # Here, we print "<doc id> | result | SAVED | <path to result.json>".
        console.emit(ctx.document_id, "result", "SAVED", output_json or "-")
        # Here, True = this document succeeded.
        return True

    # Here, TASK 2: run ALL documents at once (bounded by the semaphore)
    # and wait until every one of them is finished.
    results = await asyncio.gather(*(process_one(pdf) for pdf in pdf_files))
    # Here, we count how many documents failed.
    failed = results.count(False)

    # Here, we print the final run summary, e.g. "2 succeeded, 0 failed".
    console.emit(
        "run",
        "summary",
        "COMPLETED",
        f"{len(pdf_files) - failed} succeeded, {failed} failed",
    )
    # Here, the shell exit code: 0 = all good, 1 = at least one failed.
    return 1 if failed else 0


def run(pdf_files: list[Path] | None = None) -> int:
    """The synchronous door to the async pipeline — used by main.py and the
    web UI (app.py). Just bridges sync -> async and returns the exit code."""
    # Here, asyncio.run starts the event loop and runs run_async to the end.
    return asyncio.run(run_async(pdf_files))
