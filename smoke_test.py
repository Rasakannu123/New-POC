"""
Smoke test for the async pipeline (Tasks 1-6).

Runs the real LangGraph pipeline against generated PDFs and a fake model
client, so retries, token limits and document concurrency can be verified
deterministically without calling the real gateway.

Usage:
    python smoke_test.py

Everything it creates lives under data/output/_smoke and is deleted at the end.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

from src import config
from src import pipeline_graph as pg
from src.extraction import ExtractionEngine

ROOT = Path(__file__).resolve().parent
WORK = config.OUTPUT_DIR / "_smoke"

MODEL_REPLY = '{"doc_type": {"value": "Invoice", "confidence": 80}}'


class FakeCreate:
    """Fake chat.completions.create: fails the first N calls, then succeeds."""

    def __init__(self, failures: int, delay: float = 0.05) -> None:
        self.failures = failures
        self.delay = delay
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.calls <= self.failures:
            raise RuntimeError("simulated API failure")
        message = SimpleNamespace(content=MODEL_REPLY)
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=30)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def fake_engine(failures: int, delay: float = 0.05) -> ExtractionEngine:
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCreate(failures, delay))
    )
    return ExtractionEngine(client=client)


def make_pdf(path: Path, pages: int) -> Path:
    """Writes a minimal valid multi-page PDF (grey rectangle per page)."""
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(pages))
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
    }
    for i in range(pages):
        content_id = 4 + 2 * i
        objects[3 + 2 * i] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 280] "
            f"/Contents {content_id} 0 R >>"
        ).encode()
        stream = b"0.5 g 20 20 160 240 re f"
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref_at = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, count):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF"
    ).encode()
    path.write_bytes(bytes(out))
    return path


def load_result(pdf: Path) -> dict:
    path = config.OUTPUT_DIR / pdf.stem / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"  PASS  {label}")


def test_token_limit() -> None:
    print("\n[test] token limit stops further model calls (Task 6)")
    config.DOCUMENT_TOKEN_LIMIT = 400
    config.LLM_PAGE_RETRY_LIMIT = 0
    pdf = make_pdf(WORK / "_smoke_tokens.pdf", 5)
    pg.ExtractionEngine = lambda *a, **k: fake_engine(failures=0)
    exit_code = pg.run([pdf])
    check(exit_code == 0, "run succeeds")
    record = load_result(pdf)
    pages = record["pages"]
    check(len(pages) == 5, "all 5 pages are in the metadata")
    check(
        all(p["status"] == "completed" for p in pages[:4]),
        "pages 1-4 completed (130+130+130+130 = 520 tokens)",
    )
    check(pages[3]["cumulative_tokens"] == 520, "cumulative tokens = 520 after page 4")
    check(pages[4]["status"] == "stopped", "page 5 is stopped")
    check(pages[4]["image"] is None, "stopped page has no image")
    check("Token limit" in pages[4]["error"], "stopped page explains the token limit")
    check(record["token_usage"]["limit_reached"], "document metadata flags the limit")
    check(
        pages[0]["token_usage"] == {
            "input_tokens": 100,
            "output_tokens": 30,
            "total_tokens": 130,
        },
        "per-page token usage (input + output)",
    )


def test_page_and_document_retry_limits() -> None:
    print("\n[test] per-page and per-document retry limits (Task 5)")
    config.DOCUMENT_TOKEN_LIMIT = 0
    config.LLM_PAGE_RETRY_LIMIT = 2
    config.LLM_DOCUMENT_RETRY_LIMIT = 3
    pdf = make_pdf(WORK / "_smoke_retries.pdf", 3)
    pg.ExtractionEngine = lambda *a, **k: fake_engine(failures=99)
    exit_code = pg.run([pdf])
    check(exit_code == 0, "run succeeds even when every call fails")
    record = load_result(pdf)
    pages = record["pages"]
    retries = [p["retries_used"] for p in pages]
    check(retries == [2, 1, 0], f"retries per page {retries} (page 2, document 3 limit)")
    check(all(p["status"] == "failed" for p in pages), "pages are marked failed")
    check(record["retry_usage"]["retries_used"] == 3, "document retries capped at 3")


def test_retry_then_success() -> None:
    print("\n[test] a failed call is retried and then succeeds (Task 5)")
    config.LLM_PAGE_RETRY_LIMIT = 2
    config.LLM_DOCUMENT_RETRY_LIMIT = 5
    pdf = make_pdf(WORK / "_smoke_retry_ok.pdf", 1)
    pg.ExtractionEngine = lambda *a, **k: fake_engine(failures=2)
    exit_code = pg.run([pdf])
    check(exit_code == 0, "run succeeds")
    record = load_result(pdf)
    page = record["pages"][0]
    check(page["status"] == "completed", "page completed after 2 retries")
    check(page["retries_used"] == 2, "retries_used = 2")
    check(page["extracted_fields"] == {"doc_type": "Invoice"}, "fields parsed")


def test_document_concurrency() -> None:
    print("\n[test] documents run together, pages one by one (Task 1)")
    config.DOCUMENT_TOKEN_LIMIT = 0
    config.LLM_PAGE_RETRY_LIMIT = 0
    config.MAX_CONCURRENT_DOCUMENTS = 2
    pdfs = [
        make_pdf(WORK / "_smoke_many.pdf", 10),
        make_pdf(WORK / "_smoke_few.pdf", 2),
        make_pdf(WORK / "_smoke_mid.pdf", 5),
    ]
    pg.ExtractionEngine = lambda *a, **k: fake_engine(failures=0, delay=0.1)
    exit_code = pg.run(pdfs)
    check(exit_code == 0, "all three documents succeed")
    records = {pdf.stem: load_result(pdf) for pdf in pdfs}
    for stem, record in records.items():
        check(
            all(p["status"] == "completed" for p in record["pages"]),
            f"{stem}: every page completed",
        )
    check(
        re.fullmatch(r"\d{4}", records["_smoke_many"]["document_id"]) is not None,
        "document IDs look like 0001",
    )
    first = records["_smoke_many"]["pages"][0]
    check(
        first["page_id"] == f'{records["_smoke_many"]["document_id"]}/01',
        "page IDs look like 0001/01",
    )
    check(
        all("total_processing_time" in p for p in records["_smoke_mid"]["pages"]),
        "total processing time stored in page metadata (Task 4)",
    )
    check(
        set(records["_smoke_few"]["node_latency"])
        == {"convert", "enhance", "assess", "route", "extract", "output"},
        "all six nodes have latency totals (Tasks 3-4)",
    )


def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    real_engine = pg.ExtractionEngine
    try:
        test_token_limit()
        test_page_and_document_retry_limits()
        test_retry_then_success()
        test_document_concurrency()
    finally:
        pg.ExtractionEngine = real_engine
        config.DOCUMENT_TOKEN_LIMIT = 100000
        config.LLM_PAGE_RETRY_LIMIT = 2
        config.LLM_DOCUMENT_RETRY_LIMIT = 5
        config.MAX_CONCURRENT_DOCUMENTS = 4
        shutil.rmtree(WORK, ignore_errors=True)
        for directory in config.OUTPUT_DIR.glob("_smoke_*"):
            if directory.is_dir() and directory.resolve().is_relative_to(
                config.OUTPUT_DIR.resolve()
            ):
                shutil.rmtree(directory, ignore_errors=True)
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
