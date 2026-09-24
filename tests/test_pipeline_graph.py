"""Tests for the LangGraph orchestration wiring."""

import asyncio
import sqlite3

from langgraph.graph import END, START, StateGraph

from src.doc_extraction.pipeline_graph import GraphPipeline, PipelineState


def test_route_after_gate_routes_needed_pages_to_extract():
    assert GraphPipeline._route_after_gate({"needed_indices": [0, 2]}) == "extract"


def test_route_after_gate_finalizes_when_nothing_needed():
    assert GraphPipeline._route_after_gate({"needed_indices": []}) == "finalize"
    assert GraphPipeline._route_after_gate({}) == "finalize"


def test_route_after_convert_finalizes_on_error():
    assert GraphPipeline._route_after_convert({"error": "boom"}) == "finalize"
    assert GraphPipeline._route_after_convert({}) == "enhance"


def test_route_after_extract_uses_grouping_mode():
    assert (
        GraphPipeline._route_after_extract({"multi_doc_field": "invoice_number"})
        == "grouping"
    )
    assert GraphPipeline._route_after_extract({"multi_doc_field": None}) == "single"


def test_compiled_stub_graph_runs_fan_out_and_join():
    order: list[str] = []

    class StubState(dict):
        value: int

    def start_node(state):
        order.append("start")
        return {"value": state["value"] + 1}

    def branch_a(state):
        order.append("a")
        return {}

    def branch_b(state):
        order.append("b")
        return {}

    def join_node(state):
        order.append("join")
        return {}

    builder = StateGraph(StubState)
    builder.add_node("start", start_node)
    builder.add_node("a", branch_a)
    builder.add_node("b", branch_b)
    builder.add_node("join", join_node)
    builder.add_edge(START, "start")
    builder.add_edge("start", "a")
    builder.add_edge("start", "b")
    builder.add_edge("a", "join")
    builder.add_edge("b", "join")
    builder.add_edge("join", END)
    graph = builder.compile()

    asyncio.run(graph.ainvoke({"value": 1}))

    assert order[0] == "start"
    assert sorted(order[1:3]) == ["a", "b"]
    assert order[3] == "join"


def test_sqlite_checkpointer_works_with_async_stream(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    class StubState(dict):
        value: int

    builder = StateGraph(StubState)
    builder.add_node("step", lambda state: {"value": state.get("value", 0) + 1})
    builder.add_edge(START, "step")
    builder.add_edge("step", END)

    async def run():
        async with AsyncSqliteSaver.from_conn_string(
            str(tmp_path / "cp.sqlite")
        ) as saver:
            graph = builder.compile(checkpointer=saver)
            await graph.ainvoke(
                {"value": 1}, config={"configurable": {"thread_id": "doc-test"}}
            )
            return [
                snapshot
                async for snapshot in graph.aget_state_history(
                    {"configurable": {"thread_id": "doc-test"}}
                )
            ]

    history = asyncio.run(run())
    assert len(history) >= 2


