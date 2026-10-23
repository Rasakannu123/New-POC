"""
Latency tracking
----------------
Measures how long every pipeline node takes, per document and per page.

Thresholds come from .env (LATENCY_THRESHOLD_<NODE>, in seconds). A node that
runs longer than its threshold is reported as OVER-THRESHOLD, but a slow node
never fails the run - the thresholds are a monitoring tool, not a gate.

The recorded timings feed the terminal status lines (src/console.py), the
overall document latency report and the total processing time stored in the
page metadata.

1. def measure(node, subject)
Purpose: Times one specific step (e.g., "enhance" for page "0001/01") and returns a timing object. Example Output:

Code block


NodeTiming(node='enhance', subject='0001/01', seconds=12.5, threshold=30.0, exceeded=False)
2. def subject_total(subject)
Purpose: Sums up all time spent on one specific page across all steps. Example Output:

Code block


45.2
(Meaning: Page '0001/01' spent 12.5s enhancing + 20s assessing + 12.7s extracting = 45.2s total)

3. def node_totals()
Purpose: Sums up time for each feature across the whole document (all pages combined). Example Output:

json


{
  "convert": 12.0, 
  "enhance": 25.0, 
  "assess": 40.0, 
  "extract": 60.0
}
(Meaning: All pages together took 12s to convert, 25s to enhance, etc.)

4. def total()
Purpose: The grand sum of all work done in the document (sum of node_totals). Example Output:

Code block


137.0
(Meaning: 12.0 + 25.0 + 40.0 + 60.0 = 137.0 seconds of CPU/work time)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from src import config


@dataclass
class NodeTiming:
    """Measured duration of one node run for one subject (document or page)."""

    node: str
    subject: str
    seconds: float = 0.0
    threshold: float = 0.0
    exceeded: bool = False

    @property
    def status(self) -> str:
        """The node's processing status for the terminal."""
        return "OVER-THRESHOLD" if self.exceeded else "OK"


class LatencyTracker:
    """Collects node timings for one document run and reports them."""

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        """Takes the per-node thresholds from .env unless the caller passes
        its own table (used by tests)."""
        self.thresholds = dict(
            thresholds if thresholds is not None else config.LATENCY_THRESHOLDS
        )
        self.timings: list[NodeTiming] = []

    @contextmanager
    def measure(self, node: str, subject: str) -> Iterator[NodeTiming]:
        """Times one node run and yields its NodeTiming - the caller prints
        the terminal line, so one aligned line carries the processing status,
        the latency and the node's result together. The timing is filled in
        even when the node raises."""
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
        """Total time spent on one subject - the processing time of one page."""
        return round(
            sum(t.seconds for t in self.timings if t.subject == subject), 2
        )

    def node_totals(self) -> dict[str, float]:
        """Processing time per node across the whole document."""
        totals: dict[str, float] = {}
        for timing in self.timings:
            totals[timing.node] = totals.get(timing.node, 0.0) + timing.seconds
        return {node: round(seconds, 2) for node, seconds in totals.items()}

    def total(self) -> float:
        """Total processing time of all nodes - the overall document latency."""
        return round(sum(t.seconds for t in self.timings), 2)
