"""Tests for the LangGraph orchestration wiring."""

import asyncio

from langgraph.graph import END, START, StateGraph

from src.doc_extraction.pipeline_graph import (
    GraphPipeline,
    PipelineState,
    RunEventBus,
    _next_or_finalize,
    _traced,
)


def test_route_after_quarantine_routes_needed_pages_to_extract():
    assert GraphPipeline._route_after_quarantine({"needed_indices": [0, 2]}) == "route"


def test_route_after_quarantine_finalizes_when_nothing_needed():
    assert GraphPipeline._route_after_quarantine({"needed_indices": []}) == "finalize"
    assert GraphPipeline._route_after_quarantine({}) == "finalize"


def test_route_after_quarantine_finalizes_on_error():
    assert (
        GraphPipeline._route_after_quarantine({"error": "boom", "needed_indices": [0]})
        == "finalize"
    )


def test_next_or_finalize_skips_to_finalize_on_error():
    route = _next_or_finalize("enhance")
    assert route({}) == "enhance"
    assert route({"error": "boom"}) == "finalize"


def _stub_graph(node):
    builder = StateGraph(PipelineState)
    builder.add_node("step", node)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile()


def test_traced_node_records_start_input_output_end():
    def node(state):
        return {"page_count": state["page_count"] + 1}

    graph = _stub_graph(_traced("step", ("page_count",))(node))

    result = asyncio.run(graph.ainvoke({"page_count": 1, "trace": []}))

    envelope = result["trace"][0]
    assert envelope["node"] == "step"
    assert envelope["seq"] == 1
    assert envelope["status"] == "ok"
    assert envelope["error"] is None
    assert envelope["input"] == {"page_count": 1}
    assert envelope["output"] == {"page_count": 2}
    assert envelope["started_at"] <= envelope["ended_at"]
    assert envelope["duration_s"] >= 0


def test_traced_node_records_errors_without_raising():
    def node(state):
        raise RuntimeError("boom")

    graph = _stub_graph(_traced("step", ())(node))

    result = asyncio.run(graph.ainvoke({"trace": []}))

    envelope = result["trace"][0]
    assert envelope["status"] == "error"
    assert envelope["error"] == "RuntimeError: boom"
    assert envelope["output"]["status"] == "failed"


def test_graph_builds_with_every_pipeline_node():
    pipeline = GraphPipeline()
    nodes = set(pipeline.builder.nodes)
    assert nodes == {
        "ingest",
        "convert",
        "enhance",
        "assess",
        "gate",
        "quarantine",
        "route",
        "extract",
        "group",
        "emit",
        "finalize",
    }


def test_sqlite_checkpointer_works_with_async_stream(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    builder = StateGraph(PipelineState)
    builder.add_node(
        "step", lambda state: {"page_count": state.get("page_count", 0) + 1}
    )
    builder.add_edge(START, "step")
    builder.add_edge("step", END)

    async def run():
        async with AsyncSqliteSaver.from_conn_string(
            str(tmp_path / "cp.sqlite")
        ) as saver:
            graph = builder.compile(checkpointer=saver)
            await graph.ainvoke(
                {"page_count": 1}, config={"configurable": {"thread_id": "doc-test"}}
            )
            return [
                snapshot
                async for snapshot in graph.aget_state_history(
                    {"configurable": {"thread_id": "doc-test"}}
                )
            ]

    history = asyncio.run(run())
    assert len(history) >= 2


def test_run_event_bus_replays_for_late_subscriber():
    bus = RunEventBus()
    bus.publish("run-1", {"type": "run_start"})
    replay, subscriber, closed = bus.subscribe("run-1")
    assert closed is False
    assert replay == [{"type": "run_start"}]
    bus.publish("run-1", {"type": "node"})
    assert subscriber.get(timeout=1) == {"type": "node"}
    bus.close("run-1")
    assert subscriber.get(timeout=1) is None
    bus.unsubscribe("run-1", subscriber)
    _, _, closed = bus.subscribe("run-1")
    assert closed is True


def test_run_event_bus_unknown_run_is_closed():
    bus = RunEventBus()
    replay, subscriber, closed = bus.subscribe("nope")
    assert closed is True
    assert subscriber is None
    assert replay == []
