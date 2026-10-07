"""
Terminal output
---------------
Every pipeline message uses one aligned line format:

    TIME | SUBJECT | NODE | STATUS | LATENCY | DETAIL

so the terminal stays readable when several documents process at the same
time and their lines interleave - each line names its document or page ID in
a fixed column. Logging output (errors, warnings) goes through the same
format, and per-request library noise stays silent.
"""

from __future__ import annotations

import logging
import time

WIDTH_SUBJECT = 8
WIDTH_NODE = 8
WIDTH_STATUS = 14
WIDTH_LATENCY = 34


def emit(
    subject: str,
    node: str,
    status: str,
    detail: str = "",
    latency: float | None = None,
    threshold: float | None = None,
) -> None:
    """Prints one aligned status line.

    latency without threshold reports the document total; latency with its
    threshold reports one node's processing status."""
    if latency is None:
        latency_text = ""
    elif threshold is None:
        latency_text = f"latency {latency:6.2f}s (document total)"
    else:
        latency_text = f"latency {latency:6.2f}s (threshold {threshold:5.1f}s)"
    stamp = time.strftime("%H:%M:%S")
    print(
        f"{stamp} | {subject:<{WIDTH_SUBJECT}} | {node:<{WIDTH_NODE}} | "
        f"{status:<{WIDTH_STATUS}} | {latency_text:<{WIDTH_LATENCY}} | {detail}"
    )


class _ConsoleHandler(logging.Handler):
    """Puts log records into the same aligned line format."""

    def emit(self, record: logging.LogRecord) -> None:
        emit("system", "log", record.levelname, self.format(record))


def install(level: int = logging.WARNING) -> None:
    """Routes all logging through the aligned console format and silences
    per-request library chatter (HTTP requests, OCR setup), because the
    pipeline's own status lines already report every model call."""
    handler = _ConsoleHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.basicConfig(level=level, handlers=[handler])
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
