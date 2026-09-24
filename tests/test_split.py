"""Tests for the local split-gate keyword matching (no model, no OCR)."""

from src.doc_extraction.layers.split import (
    VERDICT_NO,
    VERDICT_YES,
    SplitEngine,
)


def test_gate_disabled_treats_page_as_needed():
    engine = SplitEngine(no_need_fields=[])
    decision = engine.classify(None)
    assert decision.verdict == VERDICT_NO
    assert decision.reason == "no_need_page gate disabled"


def test_exact_match_after_normalization():
    engine = SplitEngine(no_need_fields=["delivery-note-no"])
    decision = engine._match_keywords("TAX INVOICE\n\nDelivery-Note No: 45871")
    assert decision.verdict == VERDICT_YES
    assert decision.raw_reply == "matched 'delivery-note-no'"


def test_fuzzy_match_survives_ocr_errors():
    engine = SplitEngine(no_need_fields=["delivery note no"])
    decision = engine._match_keywords("Deiivery Note N0 45871\n\nQty: 2")
    assert decision.verdict == VERDICT_YES
    assert "similarity" in decision.reason


def test_fuzzy_match_ignores_case_and_hyphens():
    engine = SplitEngine(no_need_fields=["DELIVERY-NOTE-NO"])
    decision = engine._match_keywords("please find the delivery note no below")
    assert decision.verdict == VERDICT_YES


def test_no_match_means_page_is_needed():
    engine = SplitEngine(no_need_fields=["delivery-note-no"])
    decision = engine._match_keywords("Tax Invoice\nTotal Amount: 100.00 AED")
    assert decision.verdict == VERDICT_NO
    assert decision.raw_reply == ""


def test_best_keyword_wins():
    engine = SplitEngine(
        no_need_fields=["supplier-address", "delivery-address"]
    )
    decision = engine._match_keywords("Supplier Address: Dubai, UAE")
    assert decision.verdict == VERDICT_YES
    assert decision.raw_reply == "matched 'supplier-address'"
