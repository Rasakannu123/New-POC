"""Tests for run tracking: registry, run endpoints and the node trace replay."""

import json

from fastapi.testclient import TestClient

from src.doc_extraction import config, pipeline_graph, server


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    return TestClient(server.app)


def _fake_trace():
    return {
        "node": "convert",
        "seq": 1,
        "started_at": "2026-02-12T10:00:01.000+00:00",
        "ended_at": "2026-02-12T10:00:02.000+00:00",
        "duration_s": 1.0,
        "status": "ok",
        "input": {"pdf_path": "data/input/doc.pdf"},
        "output": {"page_count": 1},
        "error": None,
    }


def _write_fake_run(run_id="doc-1", **overrides):
    record = {
        "run_id": run_id,
        "document": "doc.pdf",
        "pdf_path": "data/input/doc.pdf",
        "status": "completed",
        "started_at": "2026-02-12T10:00:00.000+00:00",
        "started_ts": 1.0,
        "finished_at": "2026-02-12T10:01:00.000+00:00",
        "error": None,
        "trace": [_fake_trace()],
    }
    record.update(overrides)
    pipeline_graph.write_run(record)
    return record


def test_write_and_read_run_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    _write_fake_run()
    assert pipeline_graph.read_run("doc-1")["run_id"] == "doc-1"
    assert pipeline_graph.read_run("nope") is None


def test_list_runs_orders_newest_first(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    _write_fake_run("old", started_ts=1.0)
    _write_fake_run("new", started_ts=2.0)
    assert [run["run_id"] for run in pipeline_graph.list_runs()] == ["new", "old"]


def test_runs_endpoints(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _write_fake_run()

    listing = client.get("/api/runs").json()
    assert [run["run_id"] for run in listing["runs"]] == ["doc-1"]

    detail = client.get("/api/runs/doc-1").json()
    assert detail["trace"][0]["node"] == "convert"
    assert detail["trace"][0]["input"] == {"pdf_path": "data/input/doc.pdf"}
    assert detail["trace"][0]["output"] == {"page_count": 1}
    assert detail["trace"][0]["started_at"] <= detail["trace"][0]["ended_at"]

    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/..%2Fruns").status_code in (400, 404)


def test_run_stream_replays_trace_for_finished_run(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _write_fake_run()

    with client.stream("GET", "/api/runs/doc-1/stream") as response:
        assert response.status_code == 200
        lines = [
            line for line in response.iter_lines() if line.startswith("data: ")
        ]

    events = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert events[0]["type"] == "node"
    assert events[0]["trace"]["node"] == "convert"
    assert events[-1]["type"] == "run_end"
    assert events[-1]["status"] == "completed"


def test_run_stream_unknown_run_404(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/runs/nope/stream").status_code == 404
