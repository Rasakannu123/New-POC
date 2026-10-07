"""
Token and retry budgets
-----------------------
Two budgets shared by every model call of one document:

- TokenBudget: cumulative input+output tokens of the whole document. When the
  limit is reached the document stops making model calls (the limits apply to
  the document as a whole, never per page).
- RetryBudget: how often a failed API call may be retried - limited per page
  AND per document, so one broken page cannot burn the whole document's
  retries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenUsage:
    """Token usage of a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenBudget:
    """Cumulative model-token budget for one document."""

    def __init__(self, limit: int) -> None:
        """limit <= 0 means unlimited."""
        self.limit = int(limit)
        self.used = 0
        self.calls: list[TokenUsage] = []

    def record(self, input_tokens: int, output_tokens: int) -> TokenUsage:
        """Adds one model call's token usage and returns it, so the caller can
        store the per-page numbers next to the cumulative total."""
        usage = TokenUsage(
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
        )
        self.used += usage.total_tokens
        self.calls.append(usage)
        return usage

    @property
    def exhausted(self) -> bool:
        """True once the cumulative usage reached (or passed) the limit."""
        return self.limit > 0 and self.used >= self.limit


class RetryBudget:
    """Per-page and per-document retry limits for failed API calls."""

    def __init__(self, page_limit: int, document_limit: int) -> None:
        """Both limits count retries (not attempts); 0 means never retry."""
        self.page_limit = max(0, int(page_limit))
        self.document_limit = max(0, int(document_limit))
        self.retries_used = 0

    def take_retry(self, page_retries_used: int) -> bool:
        """Grants one retry when the page limit and the document limit both
        still allow it; the granted retry is deducted from the document."""
        if page_retries_used >= self.page_limit:
            return False
        if self.retries_used >= self.document_limit:
            return False
        self.retries_used += 1
        return True
