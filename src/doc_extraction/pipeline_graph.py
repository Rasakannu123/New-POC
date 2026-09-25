"""
LangGraph pipeline orchestration
--------------------------------
One PDF is one LangGraph run (thread_id = run_id). Every pipeline step is a
separate node and a checkpoint is written at every node boundary via the
configured checkpointer (sqlite by default):

    START -> ingest -> convert -> enhance -> assess -> gate -> quarantine
        -> route -> extract -> group -> emit -> finalize -> END

Each node reports start / input / output / end through a NodeTrace envelope
carried in the graph state (channel "trace"), which the review UI renders
and the run registry (data/runs/<run_id>/run.json) persists.

State holds JSON-safe summaries and file paths only - page images live under
data/runs/<run_id>/pages/ - so checkpoints stay small and renderable.

The process pool, the assess thread pool and the async extraction semaphore
stay inside the nodes: they are execution details, not graph concepts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import operator
import queue
import shutil
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from src.doc_extraction import config
from src.doc_extraction.cost import cost_block
from src.doc_extraction.layers.extraction import ExtractionResult
from src.doc_extraction.layers.grouping import group_pages_by_value
from src.doc_extraction.layers.preprocessing import preprocess_page_bytes
from src.doc_extraction.layers.quality import QualityAssessment
from src.doc_extraction.layers.router import RoutingDecision
from src.doc_extraction.layers.split import (
    VERDICT_NO,
    VERDICT_UNCLEAR,
    VERDICT_YES,
    SplitDecision,
)
from src.doc_extraction.pipeline import Pipeline

logger = logging.getLogger("pipeline_graph")

SUPPORTED_EXTENSIONS = {".pdf"}

_CHECKPOINT_RUNNER: "GraphPipeline | None" = None

SUMMARY_KEYS = (
    "status",
    "error",
    "page_count",
    "document_count",
    "skipped_count",
    "review_count",
    "files",
    "totals",
    "cost",
)


class NodeTrace(TypedDict):
    node: str
    seq: int
    started_at: str
    ended_at: str
    duration_s: float
    status: str
    input: dict
    output: dict
    error: str | None


class PipelineState(TypedDict, total=False):
    run_id: str
    pdf_path: str
    document: str
    pages_dir: str
    started_at: str
    started: float
    finished_at: str
    multi_doc_field: str | None
    page_count: int
    pad: int
    pages: list[dict]
    enhance_reports: list[dict]
    assessments: list[dict]
    gate_decisions: list[dict]
    needed_indices: list[int]
    skipped_count: int
    review_count: int
    routing: list[dict]
    extractions: list[dict]
    doc_groups: list[dict]
    group_review_pages: list[int]
    document_count: int
    files: list[str]
    totals: dict
    cost: dict
    status: str
    error: str | None
    elapsed_s: float
    trace: Annotated[list[NodeTrace], operator.add]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _assessment(item: dict) -> QualityAssessment:
    return QualityAssessment(
        score=item["score"], tier=item["tier"], metrics=item.get("metrics", {})
    )


def _extraction(item: dict) -> ExtractionResult:
    return ExtractionResult(
        fields=item.get("fields", {}),
        confidence_scores=item.get("field_confidence_scores", {}),
        helper_values=item.get("helper_values", {}),
        input_tokens=item.get("input_tokens", 0),
        output_tokens=item.get("output_tokens", 0),
        model=item.get("model", ""),
        processing_time=item.get("processing_time_seconds", 0.0),
        success=item.get("success", False),
        error=item.get("error"),
        raw_response=item.get("raw_response", ""),
    )


def _next_or_finalize(next_node: str) -> Callable[[PipelineState], str]:
    def route(state: PipelineState) -> str:
        return "finalize" if state.get("error") else next_node

    route.__name__ = f"to_{next_node}"
    return route


def _traced(name: str, reads: tuple[str, ...]) -> Callable:
    def decorate(fn: Callable) -> Callable:
        def build(state, update, started_at, started, error) -> NodeTrace:
            return NodeTrace(
                node=name,
                seq=len(state.get("trace", [])) + 1,
                started_at=started_at,
                ended_at=_now(),
                duration_s=round(time.perf_counter() - started, 3),
                status="error" if error else "ok",
                input={key: state[key] for key in reads if key in state},
                output={
                    key: value for key, value in update.items() if key != "trace"
                },
                error=error,
            )

        def announce(state, started_at) -> None:
            run_id = state.get("run_id")
            if run_id:
                RUN_EVENTS.publish(
                    run_id,
                    {
                        "type": "node_start",
                        "run_id": run_id,
                        "node": name,
                        "started_at": started_at,
                    },
                )

        def execute(args) -> dict:
            state = args[-1]
            started_at = _now()
            started = time.perf_counter()
            announce(state, started_at)
            try:
                update = fn(*args)
            except Exception as exc:
                update = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "status": "failed",
                }
            error = update.get("error")
            return {
                **update,
                "trace": [
                    build(state, update, started_at, started, error)
                ],
            }

        async def execute_async(args) -> dict:
            state = args[-1]
            started_at = _now()
            started = time.perf_counter()
            announce(state, started_at)
            try:
                update = await fn(*args)
            except Exception as exc:
                update = {
                    "error": f"{type(exc).__name__}: {exc}",
                    "status": "failed",
                }
            error = update.get("error")
            return {
                **update,
                "trace": [
                    build(state, update, started_at, started, error)
                ],
            }

        if asyncio.iscoroutinefunction(fn):

            async def async_wrapper(*args) -> dict:
                return await execute_async(args)

            return async_wrapper

        def wrapper(*args) -> dict:
            return execute(args)

        return wrapper

    return decorate


class RunEventBus:
    """Fan-out of run events to live subscribers, with replay for late joins."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, dict] = {}

    def publish(self, run_id: str, event: dict) -> None:
        with self._lock:
            entry = self._runs.setdefault(
                run_id, {"events": [], "queues": [], "closed": False}
            )
            if entry["closed"]:
                return
            entry["events"].append(event)
            for subscriber in entry["queues"]:
                subscriber.put(event)

    def subscribe(self, run_id: str) -> tuple[list[dict], Any, bool]:
        with self._lock:
            entry = self._runs.get(run_id)
            if entry is None or entry["closed"]:
                return list(entry["events"]) if entry else [], None, True
            subscriber: queue.Queue = queue.Queue()
            entry["queues"].append(subscriber)
            return list(entry["events"]), subscriber, False

    def unsubscribe(self, run_id: str, subscriber: Any) -> None:
        if subscriber is None:
            return
        with self._lock:
            entry = self._runs.get(run_id)
            if entry and subscriber in entry["queues"]:
                entry["queues"].remove(subscriber)

    def close(self, run_id: str) -> None:
        with self._lock:
            entry = self._runs.setdefault(
                run_id, {"events": [], "queues": [], "closed": True}
            )
            entry["closed"] = True
            for subscriber in entry["queues"]:
                subscriber.put(None)

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            entry = self._runs.get(run_id)
            return bool(entry) and not entry["closed"]


RUN_EVENTS = RunEventBus()


def _run_dir(run_id: str) -> Path:
    return config.RUNS_DIR / run_id


def write_run(record: dict) -> None:
    directory = _run_dir(record["run_id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def read_run(run_id: str) -> dict | None:
    path = _run_dir(run_id) / "run.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_runs() -> list[dict]:
    if not config.RUNS_DIR.is_dir():
        return []
    records = []
    for directory in config.RUNS_DIR.iterdir():
        if not directory.is_dir():
            continue
        record = read_run(directory.name)
        if record:
            records.append(record)
    records.sort(key=lambda record: record.get("started_ts") or 0.0, reverse=True)
    return records


def clear_run_registry() -> int:
    if not config.RUNS_DIR.is_dir():
        return 0
    directories = [entry for entry in config.RUNS_DIR.iterdir() if entry.is_dir()]
    for directory in directories:
        record = read_run(directory.name)
        if (
            record
            and record.get("status") == "running"
            and RUN_EVENTS.is_active(directory.name)
        ):
            raise RuntimeError(f"run '{directory.name}' is still running")
    for directory in directories:
        shutil.rmtree(directory, ignore_errors=True)
    if config.CHECKPOINT_DB.is_file():
        config.CHECKPOINT_DB.unlink()
    return len(directories)


def _new_run_id(pdf_path: Path) -> str:
    base = f"{pdf_path.stem}-{time.strftime('%Y%m%d-%H%M%S')}"
    run_id = base
    suffix = 2
    while _run_dir(run_id).exists():
        run_id = f"{base}-{suffix}"
        suffix += 1
    return run_id


class GraphPipeline:
    """LangGraph orchestration of the document extraction pipeline."""

    def __init__(
        self,
        preprocess_pool: ProcessPoolExecutor | None = None,
        assess_pool: ThreadPoolExecutor | None = None,
        page_semaphore: int | None = None,
    ) -> None:
        self.writer = Pipeline(preprocess_pool, assess_pool, page_semaphore)
        self.builder = self._build_graph()

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(PipelineState)
        builder.add_node("ingest", self._ingest_node)
        builder.add_node("convert", self._convert_node)
        builder.add_node("enhance", self._enhance_node)
        builder.add_node("assess", self._assess_node)
        builder.add_node("gate", self._gate_node)
        builder.add_node("quarantine", self._quarantine_node)
        builder.add_node("route", self._route_node)
        builder.add_node("extract", self._extract_node)
        builder.add_node("group", self._group_node)
        builder.add_node("emit", self._emit_node)
        builder.add_node("finalize", self._finalize_node)

        builder.add_edge(START, "ingest")
        builder.add_conditional_edges(
            "ingest", _next_or_finalize("convert"), {"convert": "convert", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "convert", _next_or_finalize("enhance"), {"enhance": "enhance", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "enhance", _next_or_finalize("assess"), {"assess": "assess", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "assess", _next_or_finalize("gate"), {"gate": "gate", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "gate", _next_or_finalize("quarantine"), {"quarantine": "quarantine", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "quarantine",
            self._route_after_quarantine,
            {"route": "route", "finalize": "finalize"},
        )
        builder.add_conditional_edges(
            "route", _next_or_finalize("extract"), {"extract": "extract", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "extract", _next_or_finalize("group"), {"group": "group", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "group", _next_or_finalize("emit"), {"emit": "emit", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "emit", _next_or_finalize("finalize"), {"finalize": "finalize"}
        )
        builder.add_edge("finalize", END)
        return builder

    @staticmethod
    def _route_after_quarantine(state: PipelineState) -> str:
        if state.get("error"):
            return "finalize"
        return "route" if state.get("needed_indices") else "finalize"

    @_traced("ingest", ("pdf_path", "run_id"))
    def _ingest_node(self, state: PipelineState) -> dict:
        pdf = Path(state["pdf_path"])
        if pdf.suffix.lower() not in SUPPORTED_EXTENSIONS or not pdf.is_file():
            return {"error": f"invalid input file: {pdf.name}", "status": "failed"}
        pages_dir = _run_dir(state["run_id"]) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        return {"document": pdf.name, "pages_dir": str(pages_dir)}

    @_traced("convert", ("pdf_path", "pages_dir"))
    def _convert_node(self, state: PipelineState) -> dict:
        pdf_path = Path(state["pdf_path"])
        logger.info("Processing: %s", pdf_path.name)
        result = self.writer.converter.convert_pages(pdf_path)
        if not result.success:
            logger.error("  -> FAILED: %s", result.error)
            return {"error": result.error or "conversion failed", "status": "failed"}
        if result.page_count == 0:
            return {"error": "document has no pages", "status": "failed"}
        pad = max(1, len(str(result.page_count)))
        pages_dir = Path(state["pages_dir"])
        pages = []
        for page_number, payload in enumerate(
            self.writer._encode_pages(result.pages), start=1
        ):
            raw_path = pages_dir / f"page-{page_number:0{pad}d}.raw.png"
            raw_path.write_bytes(payload)
            pages.append({"page": page_number, "raw": str(raw_path)})
        return {"page_count": result.page_count, "pad": pad, "pages": pages}

    @_traced("enhance", ("pages", "pad"))
    def _enhance_node(self, state: PipelineState) -> dict:
        pad = state["pad"]
        pages_dir = Path(state["pages_dir"])
        futures = [
            self.writer.preprocess_pool.submit(
                preprocess_page_bytes, Path(page["raw"]).read_bytes()
            )
            for page in state["pages"]
        ]
        pages = []
        reports = []
        for page, future in zip(state["pages"], futures):
            enhanced, pre_binarize, angle, steps = future.result()
            page_number = page["page"]
            enhanced_path = (
                pages_dir / f"page-{page_number:0{pad}d}.{config.IMAGE_FORMAT}"
            )
            pre_path = pages_dir / f"page-{page_number:0{pad}d}.pre.png"
            enhanced_path.write_bytes(enhanced)
            pre_path.write_bytes(pre_binarize)
            pages.append(
                {
                    **page,
                    "enhanced": str(enhanced_path),
                    "pre_binarize": str(pre_path),
                }
            )
            reports.append(
                {"page": page_number, "deskew_angle": angle, "steps": steps}
            )
        return {"pages": pages, "enhance_reports": reports}

    @_traced("assess", ("pages",))
    def _assess_node(self, state: PipelineState) -> dict:
        futures = [
            self.writer.assess_pool.submit(
                self.writer._assess, Path(page["pre_binarize"]).read_bytes()
            )
            for page in state["pages"]
        ]
        assessments = []
        for page, future in zip(state["pages"], futures):
            result = future.result()
            assessments.append(
                {
                    "page": page["page"],
                    "score": result.score,
                    "tier": result.tier,
                    "metrics": result.metrics,
                }
            )
        return {"assessments": assessments}

    @_traced("gate", ("pages",))
    def _gate_node(self, state: PipelineState) -> dict:
        pages = state["pages"]
        if self.writer.split_engine.enabled:
            futures = [
                self.writer.assess_pool.submit(
                    self.writer._classify, Path(page["pre_binarize"]).read_bytes()
                )
                for page in pages
            ]
            decisions = [future.result() for future in futures]
        else:
            decisions = [
                SplitDecision(verdict=VERDICT_NO, reason="no_need_page gate disabled")
                for _ in pages
            ]
        gate_decisions = [
            {
                "page": page["page"],
                "verdict": decision.verdict,
                "raw_reply": decision.raw_reply,
                "reason": decision.reason,
            }
            for page, decision in zip(pages, decisions)
        ]
        return {"gate_decisions": gate_decisions}

    @_traced("quarantine", ("pages", "assessments", "gate_decisions", "pad"))
    def _quarantine_node(self, state: PipelineState) -> dict:
        source_pdf = Path(state["pdf_path"])
        pad = state["pad"]
        skipped_count = 0
        review_count = 0
        needed_indices: list[int] = []
        for item in state["gate_decisions"]:
            page_number = item["page"]
            index = page_number - 1
            page = state["pages"][index]
            assessment = _assessment(state["assessments"][index])
            decision = SplitDecision(
                verdict=item["verdict"],
                raw_reply=item["raw_reply"],
                reason=item["reason"],
            )
            enhanced = Path(page["enhanced"]).read_bytes()
            if item["verdict"] == VERDICT_YES:
                self.writer._write_skipped_page(
                    source_pdf, page_number, pad, enhanced, assessment, decision
                )
                skipped_count += 1
            elif item["verdict"] == VERDICT_UNCLEAR:
                self.writer._write_manual_review_page(
                    source_pdf, page_number, pad, enhanced, assessment, decision
                )
                review_count += 1
            else:
                needed_indices.append(index)
        return {
            "skipped_count": skipped_count,
            "review_count": review_count,
            "needed_indices": needed_indices,
        }

    @_traced("route", ("assessments", "needed_indices"))
    def _route_node(self, state: PipelineState) -> dict:
        routing = []
        for index in state["needed_indices"]:
            assessment = _assessment(state["assessments"][index])
            decision = self.writer.router.route(assessment)
            routing.append(
                {
                    "page": index + 1,
                    "model": decision.model,
                    "tier": decision.tier,
                    "score": decision.score,
                    "reason": decision.reason,
                }
            )
        return {"routing": routing}

    @_traced("extract", ("pages", "routing", "needed_indices"))
    async def _extract_node(self, state: PipelineState) -> dict:
        routing_by_page = {item["page"]: item for item in state["routing"]}
        jobs = []
        for index in state["needed_indices"]:
            page = state["pages"][index]
            item = routing_by_page[page["page"]]
            decision = RoutingDecision(
                model=item["model"],
                tier=item["tier"],
                score=item["score"],
                reason=item["reason"],
            )
            jobs.append((page["page"], decision, Path(page["enhanced"])))
        results = await self.writer.extract_pages(jobs)
        extractions = [
            {
                "page": page_number,
                "fields": result.fields,
                "field_confidence_scores": result.confidence_scores,
                "helper_values": result.helper_values,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "processing_time_seconds": result.processing_time,
                "success": result.success,
                "error": result.error,
                "raw_response": result.raw_response,
            }
            for (page_number, _decision, _path), result in zip(jobs, results)
        ]
        return {"extractions": extractions}

    @_traced("group", ("extractions", "multi_doc_field"))
    def _group_node(self, state: PipelineState) -> dict:
        helper = state.get("multi_doc_field")
        values: dict[int, object] = {}
        for item in state["extractions"]:
            raw = item["helper_values"].get(helper) if helper else None
            values[item["page"]] = raw.strip() if isinstance(raw, str) else raw
        if helper:
            grouping = group_pages_by_value(values)
            doc_groups = [
                {"value": document.value, "pages": document.pages}
                for document in grouping.documents
            ]
            group_review_pages = list(grouping.manual_review)
        else:
            doc_groups = [
                {"value": Path(state["pdf_path"]).stem, "pages": sorted(values)}
            ]
            group_review_pages = []
        return {
            "doc_groups": doc_groups,
            "group_review_pages": group_review_pages,
        }

    @_traced("emit", ("pages", "assessments", "extractions", "doc_groups", "group_review_pages"))
    def _emit_node(self, state: PipelineState) -> dict:
        source_pdf = Path(state["pdf_path"])
        extractions = {}
        for item in state["extractions"]:
            index = item["page"] - 1
            extractions[index] = (
                Path(state["pages"][index]["enhanced"]).read_bytes(),
                _assessment(state["assessments"][index]),
                _extraction(item),
            )
        if state.get("multi_doc_field"):
            document_count, grouped_review = self.writer._write_multi_doc_results(
                source_pdf, state["pad"], state["needed_indices"], extractions
            )
            review_count = state.get("review_count", 0) + grouped_review
            files = [
                f"{source_pdf.stem}/invoice-{index}.pdf"
                for index in range(1, document_count + 1)
            ]
        else:
            document_count = self.writer._write_single_doc_results(
                source_pdf, state["needed_indices"], extractions
            )
            review_count = state.get("review_count", 0)
            files = (
                [f"{source_pdf.stem}/{source_pdf.stem}.pdf"] if document_count else []
            )
        return {
            "document_count": document_count,
            "review_count": review_count,
            "files": files,
        }

    @_traced("finalize", ("page_count", "needed_indices", "skipped_count", "review_count", "document_count"))
    def _finalize_node(self, state: PipelineState) -> dict:
        elapsed_s = round(time.perf_counter() - state["started"], 2)
        error = state.get("error")
        totals = {
            "pages": state.get("page_count", 0),
            "extracted": len(state.get("needed_indices", [])),
            "skipped": state.get("skipped_count", 0),
            "manual_review": state.get("review_count", 0),
            "documents": state.get("document_count", 0),
        }
        cost = cost_block(
            [
                {
                    "model": item.get("model", ""),
                    "input_tokens": item.get("input_tokens", 0),
                    "output_tokens": item.get("output_tokens", 0),
                }
                for item in state.get("extractions", [])
            ]
        )
        if not error:
            logger.info("  -> %d document PDF(s) written", totals["documents"])
            logger.info(
                "  -> OK: %d page(s) in %.2fs (%d extracted, %d skipped, %d manual-review)",
                totals["pages"],
                elapsed_s,
                totals["extracted"],
                totals["skipped"],
                totals["manual_review"],
            )
        return {
            "elapsed_s": elapsed_s,
            "status": "failed" if error else "completed",
            "totals": totals,
            "cost": cost,
            "finished_at": _now(),
        }

    async def run_documents(self, pdf_paths: list[Path]) -> list[dict]:
        async with AsyncExitStack() as stack:
            if config.CHECKPOINTER == "sqlite":
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                config.CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
                saver = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(config.CHECKPOINT_DB))
                )
            else:
                from langgraph.checkpoint.memory import MemorySaver

                saver = MemorySaver()
            graph = self.builder.compile(checkpointer=saver)
            slots = asyncio.Semaphore(config.MAX_CONCURRENT_DOCUMENTS)
            results = await asyncio.gather(
                *[self._run_one(graph, slots, pdf) for pdf in pdf_paths]
            )
            return list(results)

    async def _run_one(self, graph, slots, pdf_path: Path) -> dict:
        run_id = _new_run_id(pdf_path)
        record = {
            "run_id": run_id,
            "document": pdf_path.name,
            "pdf_path": str(pdf_path),
            "status": "running",
            "started_at": _now(),
            "started_ts": time.time(),
            "finished_at": None,
            "error": None,
            "trace": [],
        }
        RUN_EVENTS.publish(
            run_id,
            {
                "type": "run_start",
                "run_id": run_id,
                "document": pdf_path.name,
                "started_at": record["started_at"],
            },
        )
        write_run(record)
        initial = {
            "run_id": run_id,
            "pdf_path": str(pdf_path),
            "started": time.perf_counter(),
            "multi_doc_field": self.writer.multi_doc_field,
            "status": "running",
            "trace": [],
        }
        try:
            async with slots:
                async for chunk in graph.astream(
                    initial,
                    config={"configurable": {"thread_id": run_id}},
                    stream_mode="updates",
                ):
                    for update in chunk.values():
                        if not update:
                            continue
                        for envelope in update.get("trace", []):
                            record["trace"].append(envelope)
                            RUN_EVENTS.publish(
                                run_id,
                                {
                                    "type": "node",
                                    "run_id": run_id,
                                    "trace": envelope,
                                },
                            )
                        for key in SUMMARY_KEYS:
                            if key in update:
                                record[key] = update[key]
                    write_run(record)
            if record.get("status", "running") == "running":
                record["status"] = "completed"
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            logger.error("  -> FAILED: %s", record["error"])
        finally:
            record["finished_at"] = _now()
            write_run(record)
            RUN_EVENTS.publish(
                run_id,
                {
                    "type": "run_end",
                    "run_id": run_id,
                    "status": record["status"],
                    "error": record.get("error"),
                    "finished_at": record["finished_at"],
                },
            )
            RUN_EVENTS.close(run_id)
        return record


def run_input_folder() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    config.INPUT_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(
        path
        for path in config.INPUT_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not pdf_files:
        logger.info(
            "No PDF documents found in '%s'. "
            "Drop PDF files into the input folder and run again.",
            config.INPUT_DIR,
        )
        return 0

    logger.info("Found %d PDF document(s) in the input folder.", len(pdf_files))

    with ProcessPoolExecutor(max_workers=config.PREPROCESS_WORKERS) as preprocess_pool, \
            ThreadPoolExecutor(max_workers=config.ASSESS_WORKERS) as assess_pool:
        runner = GraphPipeline(
            preprocess_pool, assess_pool, config.MAX_CONCURRENT_PAGES
        )
        records = asyncio.run(runner.run_documents(pdf_files))

    succeeded = sum(1 for record in records if record.get("status") == "completed")
    failed = len(records) - succeeded
    total_images = sum(record.get("page_count", 0) for record in records)
    logger.info(
        "Done. %d document(s) succeeded, %d failed, %d image(s) written to '%s'.",
        succeeded,
        failed,
        total_images,
        config.OUTPUT_DIR,
    )
    return 1 if failed else 0


async def _aload_checkpoint_history(thread_id: str) -> list[dict]:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    global _CHECKPOINT_RUNNER
    if _CHECKPOINT_RUNNER is None:
        _CHECKPOINT_RUNNER = GraphPipeline()
    runner = _CHECKPOINT_RUNNER

    async with AsyncSqliteSaver.from_conn_string(
        str(config.CHECKPOINT_DB)
    ) as saver:
        graph = runner.builder.compile(checkpointer=saver)
        snapshots = [
            snapshot
            async for snapshot in graph.aget_state_history(
                {"configurable": {"thread_id": thread_id}}
            )
        ]

    history = []
    for step, snapshot in enumerate(reversed(snapshots), start=1):
        metadata = snapshot.metadata or {}
        writes = metadata.get("writes") or {}
        configurable = (snapshot.config or {}).get("configurable", {})
        history.append(
            {
                "step": step,
                "checkpoint_id": configurable.get("checkpoint_id"),
                "node": next(iter(writes), ""),
                "next": list(snapshot.next),
                "writes": {
                    node: sorted(update) for node, update in writes.items() if update
                },
                "values": snapshot.values,
            }
        )
    return history


def load_checkpoint_history(thread_id: str) -> list[dict]:
    """Return one entry per checkpoint (node step) for a document thread."""
    if config.CHECKPOINTER != "sqlite":
        return []
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        return loop.run_until_complete(_aload_checkpoint_history(thread_id))
    return asyncio.run(_aload_checkpoint_history(thread_id))
