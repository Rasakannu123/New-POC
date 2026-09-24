"""
LangGraph pipeline orchestration
--------------------------------
Runs one PDF through the same stages as pipeline.Pipeline, expressed as a
LangGraph StateGraph:

    START -> convert -> {score + gate fan-out} -> quarantine
        -> [needed pages?] -> extract -> [grouping mode?] -> grouping|single
        -> finalize -> END

Quarantine writes (skip folder / Manual-Review) happen in the quarantine
node, exactly matching pipeline.Pipeline behaviour. The process pool, the
assess thread pool, the OCR semaphores and the async extraction semaphore
stay inside the nodes - they are execution details, not graph concepts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.doc_extraction import config
from src.doc_extraction.layers.preprocessing import preprocess_page_bytes
from src.doc_extraction.layers.split import (
    VERDICT_NO,
    VERDICT_UNCLEAR,
    VERDICT_YES,
    SplitDecision,
)
from src.doc_extraction.pipeline import Pipeline

logger = logging.getLogger("pipeline_graph")

_CHECKPOINT_RUNNER: "GraphPipeline | None" = None


class PipelineState(TypedDict, total=False):
    pdf_path: str
    source_name: str
    page_count: int
    pad: int
    pages: list
    preprocessed: list[tuple]
    assessments: list
    split_decisions: list
    needed_indices: list[int]
    extractions: dict
    skipped_count: int
    review_count: int
    document_count: int
    multi_doc_field: str | None
    error: str | None
    started: float
    elapsed: float


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
        self.graph = None
        if config.CHECKPOINTER != "sqlite":
            from langgraph.checkpoint.memory import MemorySaver

            self.graph = self.builder.compile(checkpointer=MemorySaver())

    def _build_graph(self):
        builder = StateGraph(PipelineState)
        builder.add_node("convert", self._convert_node)
        builder.add_node("enhance", self._enhance_node)
        builder.add_node("score", self._score_node)
        builder.add_node("gate", self._gate_node)
        builder.add_node("quarantine", self._quarantine_node)
        builder.add_node("extract", self._extract_node)
        builder.add_node("grouping", self._grouping_node)
        builder.add_node("single", self._single_node)
        builder.add_node("finalize", self._finalize_node)

        builder.add_edge(START, "convert")
        builder.add_conditional_edges(
            "convert", self._route_after_convert, {"enhance": "enhance", "finalize": "finalize"}
        )
        builder.add_edge("enhance", "score")
        builder.add_edge("enhance", "gate")
        builder.add_edge("score", "quarantine")
        builder.add_edge("gate", "quarantine")
        builder.add_conditional_edges(
            "quarantine", self._route_after_gate, {"extract": "extract", "finalize": "finalize"}
        )
        builder.add_conditional_edges(
            "extract", self._route_after_extract, {"grouping": "grouping", "single": "single"}
        )
        builder.add_edge("grouping", "finalize")
        builder.add_edge("single", "finalize")
        builder.add_edge("finalize", END)
        return builder

    @staticmethod
    def _route_after_convert(state: PipelineState) -> str:
        return "finalize" if state.get("error") else "enhance"

    @staticmethod
    def _route_after_gate(state: PipelineState) -> str:
        return "extract" if state.get("needed_indices") else "finalize"

    @staticmethod
    def _route_after_extract(state: PipelineState) -> str:
        return "grouping" if state.get("multi_doc_field") else "single"

    def _convert_node(self, state: PipelineState) -> dict:
        pdf_path = Path(state["pdf_path"])
        logger.info("Processing: %s", pdf_path.name)
        result = self.writer.converter.convert_pages(pdf_path)
        if not result.success:
            logger.error("  -> FAILED: %s", result.error)
            return {"error": result.error or "conversion failed"}
        if result.page_count == 0:
            return {"error": "document has no pages", "page_count": 0}
        return {
            "source_name": pdf_path.name,
            "page_count": result.page_count,
            "pad": max(1, len(str(result.page_count))),
            "pages": result.pages,
        }

    def _enhance_node(self, state: PipelineState) -> dict:
        page_bytes = self.writer._encode_pages(state["pages"])
        enhanced_futures = [
            self.writer.preprocess_pool.submit(preprocess_page_bytes, payload)
            for payload in page_bytes
        ]
        preprocessed = [future.result() for future in enhanced_futures]
        return {"preprocessed": preprocessed}

    def _score_node(self, state: PipelineState) -> dict:
        assessments = [
            self.writer.assess_pool.submit(self.writer._assess, pre_binarize)
            for (_enhanced, pre_binarize, _angle, _steps) in state["preprocessed"]
        ]
        return {"assessments": [future.result() for future in assessments]}

    def _gate_node(self, state: PipelineState) -> dict:
        preprocessed = state["preprocessed"]
        if self.writer.split_engine.enabled:
            split_futures = [
                self.writer.assess_pool.submit(self.writer._classify, pre_binarize)
                for (_enhanced, pre_binarize, _angle, _steps) in preprocessed
            ]
            split_decisions = [future.result() for future in split_futures]
        else:
            split_decisions = [
                SplitDecision(
                    verdict=VERDICT_NO, reason="no_need_page gate disabled"
                )
                for _ in preprocessed
            ]
        return {"split_decisions": split_decisions}

    def _quarantine_node(self, state: PipelineState) -> dict:
        source_pdf = Path(state["pdf_path"])
        pad = state["pad"]
        skipped_count = 0
        review_count = 0
        needed_indices: list[int] = []
        decisions = state["split_decisions"]
        for page_number, decision in enumerate(decisions, start=1):
            index = page_number - 1
            if decision.verdict == VERDICT_YES:
                self.writer._write_skipped_page(
                    source_pdf,
                    page_number,
                    pad,
                    state["preprocessed"][index][0],
                    state["assessments"][index],
                    decision,
                )
                skipped_count += 1
            elif decision.verdict == VERDICT_UNCLEAR:
                self.writer._write_manual_review_page(
                    source_pdf,
                    page_number,
                    pad,
                    state["preprocessed"][index][0],
                    state["assessments"][index],
                    decision,
                )
                review_count += 1
            else:
                needed_indices.append(index)
        return {
            "skipped_count": skipped_count,
            "review_count": review_count,
            "needed_indices": needed_indices,
        }

    async def _extract_node(self, state: PipelineState) -> dict:
        needed_indices = state["needed_indices"]
        extracted = await self.writer._extract_all(
            state["preprocessed"], state["assessments"], needed_indices
        )
        return {"extractions": dict(zip(needed_indices, extracted))}

    def _grouping_node(self, state: PipelineState) -> dict:
        document_count, grouped_review = self.writer._write_multi_doc_results(
            Path(state["pdf_path"]),
            state["pad"],
            state["needed_indices"],
            state["extractions"],
        )
        return {
            "document_count": document_count,
            "review_count": state.get("review_count", 0) + grouped_review,
        }

    def _single_node(self, state: PipelineState) -> dict:
        document_count = self.writer._write_single_doc_results(
            Path(state["pdf_path"]),
            state["needed_indices"],
            state["extractions"],
        )
        return {"document_count": document_count}

    def _finalize_node(self, state: PipelineState) -> dict:
        elapsed = round(time.perf_counter() - state["started"], 2)
        if not state.get("error"):
            logger.info(
                "  -> %d document PDF(s) written", state.get("document_count", 0)
            )
            logger.info(
                "  -> OK: %d page(s) in %.2fs (%d extracted, %d skipped, %d manual-review)",
                state.get("page_count", 0),
                elapsed,
                len(state.get("needed_indices", [])),
                state.get("skipped_count", 0),
                state.get("review_count", 0),
            )
        return {"elapsed": elapsed}

    async def _stream_with_saver(
        self, initial: dict[str, Any], thread_id: str, saver
    ) -> dict[str, Any]:
        graph = self.builder.compile(checkpointer=saver)
        invocation = {"configurable": {"thread_id": thread_id}}
        final: dict[str, Any] = {}
        async for chunk in graph.astream(initial, config=invocation, stream_mode="updates"):
            for node, update in chunk.items():
                if node and update:
                    logger.info(
                        "[step] %-11s -> %s",
                        node,
                        ", ".join(sorted(update.keys())),
                    )
                    final.update(update)
        return final

    async def _stream_graph(self, initial: dict[str, Any], thread_id: str) -> dict[str, Any]:
        if config.CHECKPOINTER == "sqlite":
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            config.CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
            async with AsyncSqliteSaver.from_conn_string(
                str(config.CHECKPOINT_DB)
            ) as saver:
                return await self._stream_with_saver(initial, thread_id, saver)
        return await self._stream_with_saver(initial, thread_id, self.graph)

    def process_pdf(self, pdf_path) -> tuple[int, int]:
        initial: dict[str, Any] = {
            "pdf_path": str(pdf_path),
            "started": time.perf_counter(),
            "multi_doc_field": self.writer.multi_doc_field,
        }
        thread_id = Path(pdf_path).stem
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        final = (
            loop.run_until_complete(self._stream_graph(initial, thread_id))
            if loop is not None
            else asyncio.run(self._stream_graph(initial, thread_id))
        )

        error = final.get("error")
        if error:
            logger.error("  -> FAILED: %s", error)
            return 0, 0
        return final.get("page_count", 0), 0


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
        history.append(
            {
                "step": step,
                "node": metadata.get("source", ""),
                "next": list(snapshot.next),
                "writes": {
                    node: sorted(update.keys()) for node, update in writes.items()
                },
                "state_keys": sorted(snapshot.values.keys()),
            }
        )
    return history


def load_checkpoint_history(thread_id: str) -> list[dict]:
    """Return one entry per checkpoint (node step) for a document thread."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        return loop.run_until_complete(_aload_checkpoint_history(thread_id))
    return asyncio.run(_aload_checkpoint_history(thread_id))

