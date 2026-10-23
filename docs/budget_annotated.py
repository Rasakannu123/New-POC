"""
budget.py — the money limits of one document, explained LINE BY LINE.
(Annotated learning copy of src/budget.py — the real source is untouched.)

It contains TWO small budgets (created once per document in DocumentContext):

    TokenBudget  (Task 6) — "how many model tokens may this document use?"
                            running total; when the limit is hit, NO more model calls.
    RetryBudget  (Task 5) — "how often may a failed API call be retried?"
                            limited per page AND per document.

Where they are used:
    created  : DocumentContext.create()  (pipeline_graph.py:180-183)
    enforced : extract_node (pipeline_graph.py:332, 347) and extraction.py:130
"""

# Here, we enable modern type hints (e.g. "int | None").
from __future__ import annotations

# Here, we import dataclass — a shortcut for "classes that are just data boxes".
from dataclasses import dataclass


# ===========================================================================
# PART 1 — TokenUsage: the receipt of ONE model call (Task 6)
# ===========================================================================

@dataclass
class TokenUsage:
    """The token numbers of a single model call — like one receipt."""

    # Here, the tokens the model READ (prompt + image), e.g. 3084.
    input_tokens: int = 0
    # Here, the tokens the model WROTE (the JSON answer), e.g. 274.
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """total_tokens lets you write usage.total_tokens instead of
        usage.input_tokens + usage.output_tokens everywhere."""
        # Here, we add both numbers: 3084 + 274 = 3358.
        return self.input_tokens + self.output_tokens


# ===========================================================================
# PART 2 — TokenBudget: the document's token wallet (Task 6)
# ===========================================================================

class TokenBudget:
    """One wallet per document: every model call spends from it."""

    def __init__(self, limit: int) -> None:
        """limit <= 0 means unlimited (no stopping)."""
        # Here, we store the limit (e.g. 5000 tokens per document).
        self.limit = int(limit)
        # Here, the running total — starts at 0 and only grows.
        self.used = 0
        # Here, we keep every receipt (not required for logic, useful for tests).
        self.calls: list[TokenUsage] = []

    def record(self, input_tokens: int, output_tokens: int) -> TokenUsage:
        """Adds ONE model call's usage to the wallet and returns the receipt,
        so the caller can store per-page numbers next to the document total."""
        # Here, we build one receipt, defending against bad values:
        usage = TokenUsage(
            # Here, "or 0" handles None, int() handles strings,
            # max(0, ...) blocks negative numbers.
            input_tokens=max(0, int(input_tokens or 0)),
            # Here, same protection for the output side.
            output_tokens=max(0, int(output_tokens or 0)),
        )
        # Here, THE SPEND: 0 -> 3358 -> 6660 -> ... (the running total).
        self.used += usage.total_tokens
        # Here, we file the receipt in the history list.
        self.calls.append(usage)
        # Here, we hand the receipt back to extract_node (goes into the record).
        return usage

    @property
    def exhausted(self) -> bool:
        """True once the document spent its whole token budget."""
        # Here, limit > 0 means "a limit is set" (0 = unlimited),
        # and used >= limit means "the wallet is empty".
        return self.limit > 0 and self.used >= self.limit


# ===========================================================================
# PART 3 — RetryBudget: the document's retry coupons (Task 5)
# ===========================================================================

class RetryBudget:
    """Two coupon books per document: retries per PAGE and retries per DOCUMENT.
    A failed API call spends one coupon from BOTH books."""

    def __init__(self, page_limit: int, document_limit: int) -> None:
        """Both limits count RETRIES (not attempts); 0 means never retry.
        Example from .env: page_limit=2, document_limit=5."""
        # Here, the per-page retry limit (max 2 retries on one page).
        self.page_limit = max(0, int(page_limit))
        # Here, the per-document retry limit (max 5 retries in the document).
        self.document_limit = max(0, int(document_limit))
        # Here, the coupons already spent by the whole document (starts 0).
        self.retries_used = 0

    def take_retry(self, page_retries_used: int) -> bool:
        """Grants ONE retry only when BOTH books still have a coupon.
        Called by extraction.py after a failed API call."""
        # Here, book 1: has THIS page used its 2 coupons already?
        if page_retries_used >= self.page_limit:
            # Here, no coupon for this page -> say NO (stop retrying this page).
            return False
        # Here, book 2: has the whole DOCUMENT used its 5 coupons already?
        if self.retries_used >= self.document_limit:
            # Here, no coupon left in the document -> say NO.
            return False
        # Here, we spend one document coupon: 0 -> 1 -> 2 ...
        self.retries_used += 1
        # Here, we say YES — the caller may retry the API call once more.
        return True
