"""Tests for the multiple-documents grouping rules."""

from src.doc_extraction.layers.grouping import group_pages_by_value


def test_consecutive_equal_values_form_documents():
    result = group_pages_by_value(
        {1: "123", 2: "123", 3: "456", 4: "2468", 5: "2468", 6: "2468"}
    )
    assert [doc.pages for doc in result.documents] == [[1, 2], [3], [4, 5, 6]]
    assert result.manual_review == []


def test_leading_nulls_go_to_manual_review():
    result = group_pages_by_value({1: None, 2: "123", 3: "123"})
    assert result.documents[0].pages == [2, 3]
    assert result.manual_review == [1]


def test_trailing_nulls_go_to_manual_review():
    result = group_pages_by_value({1: "123", 2: "123", 3: None})
    assert result.documents[0].pages == [1, 2]
    assert result.manual_review == [3]


def test_nulls_between_equal_values_join_the_document():
    result = group_pages_by_value({1: "123", 2: None, 3: "123"})
    assert result.documents[0].pages == [1, 2, 3]
    assert result.manual_review == []


def test_nulls_between_different_values_go_to_manual_review():
    result = group_pages_by_value({1: "123", 2: None, 3: "456"})
    assert [doc.pages for doc in result.documents] == [[1], [3]]
    assert result.manual_review == [2]


def test_multiple_nulls_between_different_values_go_to_manual_review():
    result = group_pages_by_value({1: "123", 2: None, 3: None, 4: "456"})
    assert [doc.pages for doc in result.documents] == [[1], [4]]
    assert result.manual_review == [2, 3]


def test_reappearing_value_goes_to_manual_review():
    result = group_pages_by_value({1: "123", 2: "456", 3: "123"})
    assert [doc.pages for doc in result.documents] == [[1], [2]]
    assert result.manual_review == [3]


def test_reappearing_run_goes_to_manual_review():
    result = group_pages_by_value({1: "123", 2: "456", 3: "456", 4: "123", 5: "123"})
    assert [doc.pages for doc in result.documents] == [[1], [2, 3]]
    assert result.manual_review == [4, 5]


def test_all_null_pages_go_to_manual_review():
    result = group_pages_by_value({1: None, 2: None})
    assert result.documents == []
    assert result.manual_review == [1, 2]


def test_whitespace_only_values_are_treated_as_null():
    result = group_pages_by_value({1: "  ", 2: "123"})
    assert result.documents[0].pages == [2]
    assert result.manual_review == [1]


def test_values_are_compared_after_trim():
    result = group_pages_by_value({1: "123", 2: " 123 "})
    assert result.documents[0].pages == [1, 2]
    assert result.manual_review == []
