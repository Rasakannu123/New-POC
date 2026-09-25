"""Tests for the minimal upload + results API."""

from fastapi.testclient import TestClient

from src.doc_extraction import config
import app as webapp


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INPUT_DIR", tmp_path / "input")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    return TestClient(webapp.app)


def test_index_serves_the_single_page(client=None):
    client = TestClient(webapp.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "DocExtract Demo" in response.text


def test_upload_rejects_non_pdf(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/upload", files=[("files", ("notes.txt", b"hello", "text/plain"))]
    )
    assert response.status_code == 422


def test_upload_saves_pdfs(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/upload", files=[("files", ("doc.pdf", b"%PDF-1.4", "application/pdf"))]
    )
    assert response.status_code == 200
    assert response.json() == {"saved": ["doc.pdf"]}
    assert (tmp_path / "input" / "doc.pdf").is_file()
    assert client.get("/api/files").json()["files"][0]["name"] == "doc.pdf"


def test_results_listing_and_detail(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    directory = tmp_path / "output" / "doc"
    directory.mkdir(parents=True)
    (directory / "result.json").write_text(
        '{"document": "doc.pdf", "pages": []}', encoding="utf-8"
    )

    listing = client.get("/api/results").json()["results"]
    assert listing[0]["name"] == "doc"
    assert client.get("/api/results/doc").json()["document"] == "doc.pdf"
    assert client.get("/api/results/nope").status_code == 404


def test_process_runs_pipeline(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    calls = []

    def fake_run(pdf_files=None):
        calls.append(pdf_files)
        return 0

    monkeypatch.setattr(webapp, "run", fake_run)
    response = client.post("/api/process")

    assert response.status_code == 200
    assert response.json()["exit_code"] == 0
    assert calls == [None]
