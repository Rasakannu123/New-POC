"""Tests for the delete endpoints of the review API."""

import json

from fastapi.testclient import TestClient

from src.doc_extraction import config, server


def _client(monkeypatch, tmp_path):
    monkeypatch.setitem(server.BUCKETS, "input", tmp_path / "input")
    monkeypatch.setitem(server.BUCKETS, "output", tmp_path / "output")
    monkeypatch.setitem(server.BUCKETS, "skip", tmp_path / "skip")
    monkeypatch.setitem(server.BUCKETS, "review", tmp_path / "review")
    return TestClient(server.app)


def test_delete_input_file(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    source = tmp_path / "input" / "doc.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4")

    response = client.delete("/api/input/doc.pdf")

    assert response.status_code == 200
    assert response.json() == {"deleted": "doc.pdf"}
    assert not source.exists()


def test_delete_input_file_missing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.delete("/api/input/nope.pdf").status_code == 404


def test_delete_document_removes_whole_folder(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    document = tmp_path / "output" / "Fruits Garden"
    document.mkdir(parents=True)
    (document / "invoice-1.pdf").write_bytes(b"%PDF")
    (document / "invoice-1.json").write_text(
        json.dumps({"file": "invoice-1.pdf"}), encoding="utf-8"
    )
    (document / "invoice-2.pdf").write_bytes(b"%PDF")

    response = client.delete("/api/document/output/Fruits Garden")

    assert response.status_code == 200
    assert not document.exists()


def test_delete_document_missing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.delete("/api/document/output/Nope").status_code == 404


def test_delete_page_removes_image_and_json(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for bucket in ("skip", "review"):
        directory = tmp_path / bucket
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "doc_1.png").write_bytes(b"png")
        (directory / "doc_1.json").write_text("{}", encoding="utf-8")

    response = client.delete("/api/page/skip/doc_1")

    assert response.status_code == 200
    assert sorted(response.json()["deleted"]) == ["doc_1.json", "doc_1.png"]
    assert not (tmp_path / "skip" / "doc_1.png").exists()
    assert (tmp_path / "review" / "doc_1.png").exists()


def test_delete_page_missing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.delete("/api/page/review/nope").status_code == 404


def test_delete_rejects_path_traversal(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    assert client.delete("/api/input/..%2Fsecret.txt").status_code in (400, 404)
    assert secret.exists()


def test_clear_input_removes_only_pdfs(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    directory = tmp_path / "input"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "a.pdf").write_bytes(b"%PDF")
    (directory / "b.pdf").write_bytes(b"%PDF")
    (directory / "notes.txt").write_text("keep", encoding="utf-8")

    response = client.delete("/api/clear/input")

    assert response.status_code == 200
    assert response.json() == {"removed": 2}
    assert not (directory / "a.pdf").exists()
    assert (directory / "notes.txt").exists()


def test_clear_output_removes_folders_and_records(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    output = tmp_path / "output"
    (output / "Doc A").mkdir(parents=True)
    (output / "Doc A" / "invoice-1.pdf").write_bytes(b"%PDF")
    (output / "Doc A" / "invoice-1.json").write_text("{}", encoding="utf-8")
    (output / "Doc B").mkdir()
    (output / "loose_1.png").write_bytes(b"png")
    (output / "loose_1.json").write_text("{}", encoding="utf-8")

    response = client.delete("/api/clear/output")

    assert response.status_code == 200
    assert response.json() == {"removed": 4}
    assert not (output / "Doc A").exists()
    assert not (output / "loose_1.png").exists()
    assert not list(output.iterdir())


def test_clear_skip_and_review(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for bucket in ("skip", "review"):
        directory = tmp_path / bucket
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "p_1.png").write_bytes(b"png")
        (directory / "p_1.json").write_text("{}", encoding="utf-8")

    assert client.delete("/api/clear/skip").json() == {"removed": 2}
    assert client.delete("/api/clear/review").json() == {"removed": 2}
    assert not (tmp_path / "skip" / "p_1.png").exists()
    assert not (tmp_path / "review" / "p_1.json").exists()


def test_put_template_drops_blank_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TEMPLATE_PATH", tmp_path / "test.json")
    client = _client(monkeypatch, tmp_path)
    response = client.put(
        "/api/template",
        json={
            "extracted_fields": {"invoice_number": "", "   ": ""},
            "no_need_page": {"delivery-note-no": ""},
            "multiple-docs": {"same-words-every-pages": {"invoice_number": "", "": ""}},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["extracted_fields"] == {"invoice_number": ""}
    assert payload["multiple-docs"]["same-words-every-pages"] == {
        "invoice_number": ""
    }
