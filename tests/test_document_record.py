"""Tests for per-document PDF output in both grouping modes."""

import json
from types import SimpleNamespace

from pypdf import PdfReader, PdfWriter

from src.doc_extraction import config
from src.doc_extraction.layers.grouping import DocumentGroup
from src.doc_extraction.pipeline import Pipeline


def _page_data(fields, confidences, model="m", success=True, error=None):
    return (
        b"",
        SimpleNamespace(score=70.0, tier="blurry"),
        SimpleNamespace(
            fields=fields,
            confidence_scores=confidences,
            model=model,
            success=success,
            processing_time=1.0,
            error=error,
            input_tokens=0,
            output_tokens=0,
        ),
    )


def _make_pdf(tmp_path, name, pages):
    src = tmp_path / name
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    with src.open("wb") as handle:
        writer.write(handle)
    return src


def test_feature_off_joins_all_pages_into_one_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    src = _make_pdf(tmp_path, "Fruits Garden.pdf", 3)
    extractions = {
        0: _page_data(
            {"invoice_number": "123", "date": None},
            {"invoice_number": 90, "date": 0},
            model="mistralai/mistral-small-2603",
        ),
        1: _page_data(
            {"invoice_number": None, "date": "2026-01-05"},
            {"invoice_number": 0, "date": 80},
            model="mistralai/mistral-small-2603",
        ),
        2: _page_data(
            {"invoice_number": None, "date": None},
            {"invoice_number": 0, "date": 0},
            model="mistralai/mistral-small-2603",
        ),
    }
    for extraction in extractions.values():
        extraction[2].input_tokens = 1_250
        extraction[2].output_tokens = 350

    count = Pipeline._write_single_doc_results(src, [0, 1, 2], extractions)

    assert count == 1
    folder = tmp_path / "Fruits Garden"
    assert (folder / "Fruits Garden.pdf").is_file()
    assert len(PdfReader(folder / "Fruits Garden.pdf").pages) == 3
    record = json.loads(
        (folder / "Fruits Garden.json").read_text(encoding="utf-8")
    )
    assert record["file"] == "Fruits Garden.pdf"
    assert record["pages"] == [1, 2, 3]
    assert record["quality_score"] == 70.0
    assert record["quality_tier"] == "blurry"
    assert record["cost"]["totals"]["input_tokens"] == 3_750
    assert record["cost"]["totals"]["output_tokens"] == 1_050
    assert record["cost"]["totals"]["input_cost"] == round(
        3_750 * 0.15 / 1_000_000, 12
    )
    assert record["cost"]["totals"]["output_cost"] == round(
        1_050 * 0.60 / 1_000_000, 12
    )
    assert record["extracted_fields"]["invoice_number"] == "123"
    assert record["extracted_fields"]["date"] == "2026-01-05"


def test_feature_on_writes_invoice_n_pdfs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    src = _make_pdf(tmp_path, "Multi.pdf", 3)
    page_data = {
        1: _page_data({"invoice_number": "123"}, {"invoice_number": 90}),
        2: _page_data({"invoice_number": "123"}, {"invoice_number": 90}),
        3: _page_data({"invoice_number": "456"}, {"invoice_number": 80}),
    }

    Pipeline._write_document(
        src, "invoice-1.pdf", DocumentGroup("123", [1, 2]), page_data
    )
    Pipeline._write_document(
        src, "invoice-2.pdf", DocumentGroup("456", [3]), page_data
    )

    assert (tmp_path / "Multi" / "invoice-1.pdf").is_file()
    assert len(PdfReader(tmp_path / "Multi" / "invoice-1.pdf").pages) == 2
    second = json.loads(
        (tmp_path / "Multi" / "invoice-2.json").read_text(encoding="utf-8")
    )
    assert second["pages"] == [3]
    assert second["extracted_fields"]["invoice_number"] == "456"
