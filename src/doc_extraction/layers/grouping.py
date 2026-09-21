"""
Document Grouping (Multiple Documents Feature)
----------------------------------------------
Groups extracted pages into documents by comparing a helper field value
(same-words-every-pages) across consecutive pages.

    equal consecutive values          -> one document
    nulls between equal values        -> join that document
    nulls at the start or the end     -> Manual-Review
    nulls between different values    -> Manual-Review
    value reappearing after a change  -> Manual-Review

Pure local logic: no model, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocumentGroup:
    """One detected document: its helper value and 1-based page numbers."""

    value: str
    pages: list[int] = field(default_factory=list)


@dataclass
class GroupingResult:
    documents: list[DocumentGroup] = field(default_factory=list)
    manual_review: list[int] = field(default_factory=list)


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def group_pages_by_value(values: dict[int, object]) -> GroupingResult:
    """Group 1-based page numbers by their helper field value."""
    result = GroupingResult()
    segments: list[dict] = []
    pending_nulls: list[int] = []
    trailing_nulls: list[int] = []

    for page in sorted(values):
        value = _clean(values[page])
        if value is None:
            if segments:
                pending_nulls.append(page)
            else:
                trailing_nulls.append(page)
            continue
        if segments and segments[-1]["value"] == value:
            segments[-1]["pages"].extend(pending_nulls)
            segments[-1]["pages"].append(page)
        else:
            segments.append(
                {"value": value, "pages": [page], "leading": list(pending_nulls)}
            )
        pending_nulls = []

    trailing_nulls.extend(pending_nulls)

    seen: set[str] = set()
    for segment in segments:
        result.manual_review.extend(segment["leading"])
        if segment["value"] in seen:
            result.manual_review.extend(segment["pages"])
        else:
            seen.add(segment["value"])
            result.documents.append(
                DocumentGroup(value=segment["value"], pages=list(segment["pages"]))
            )

    result.manual_review.extend(trailing_nulls)
    return result
