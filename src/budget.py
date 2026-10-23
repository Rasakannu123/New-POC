from dataclasses import dataclass


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TokenBudget:
    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self.used = 0

    def record(self, input_tokens: int, output_tokens: int) -> TokenUsage:
        usage = TokenUsage(
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
        )
        self.used += usage.total_tokens
        return usage

    @property
    def exhausted(self) -> bool:
        return self.limit > 0 and self.used >= self.limit


class RetryBudget:
    def __init__(self, page_limit: int, document_limit: int) -> None:
        self.page_limit = max(0, int(page_limit))
        self.document_limit = max(0, int(document_limit))
        self.retries_used = 0

    def take_retry(self, page_retries_used: int) -> bool:
        if page_retries_used >= self.page_limit or self.retries_used >= self.document_limit:
            return False
        self.retries_used += 1
        return True
