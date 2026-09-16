"""Tests for the split gate verdict parsing (no external services)."""

from src.doc_extraction.layers.split import (
    VERDICT_NO,
    VERDICT_UNCLEAR,
    VERDICT_YES,
    SplitEngine,
)


def test_parse_verdict_exact():
    assert SplitEngine._parse_verdict("yes") == VERDICT_YES
    assert SplitEngine._parse_verdict("no") == VERDICT_NO


def test_parse_verdict_with_punctuation_and_case():
    assert SplitEngine._parse_verdict("YES.") == VERDICT_YES
    assert SplitEngine._parse_verdict("No.") == VERDICT_NO


def test_parse_verdict_last_match_wins():
    assert (
        SplitEngine._parse_verdict("The label appears, so the final answer: yes")
        == VERDICT_YES
    )
    assert SplitEngine._parse_verdict("yes or no? final: no") == VERDICT_NO


def test_parse_verdict_unclear():
    assert SplitEngine._parse_verdict("The page is not needed") == VERDICT_UNCLEAR
    assert SplitEngine._parse_verdict("") == VERDICT_UNCLEAR


def test_gate_disabled_treats_page_as_needed():
    engine = SplitEngine(no_need_fields=[])
    decision = engine.classify(None)
    assert decision.verdict == VERDICT_NO
    assert decision.reason == "no_need_page gate disabled"
