import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass
class NodeTiming:
    node: str
    subject: str
    seconds: float = 0.0
    threshold: float = 0.0
    exceeded: bool = False

    @property
    def status(self) -> str:
        return "OVER-THRESHOLD" if self.exceeded else "OK"


class LatencyTracker:
    def __init__(self, thresholds: dict[str, float]) -> None:
        self.thresholds = dict(thresholds)
        self.timings: list[NodeTiming] = []

    @contextmanager
    def measure(self, node: str, subject: str) -> Iterator[NodeTiming]:
        timing = NodeTiming(
            node=node, subject=subject, threshold=self.thresholds.get(node, 0.0)
        )
        started = time.perf_counter()
        try:
            yield timing
        finally:
            timing.seconds = round(time.perf_counter() - started, 2)
            timing.exceeded = (
                timing.threshold > 0 and timing.seconds > timing.threshold
            )
            self.timings.append(timing)

    def subject_total(self, subject: str) -> float:
        return round(
            sum(t.seconds for t in self.timings if t.subject == subject), 2
        )

    def node_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for timing in self.timings:
            totals[timing.node] = totals.get(timing.node, 0.0) + timing.seconds
        return {node: round(seconds, 2) for node, seconds in totals.items()}

    def total(self) -> float:
        return round(sum(t.seconds for t in self.timings), 2)
