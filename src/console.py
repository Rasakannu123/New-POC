import logging
import time


def emit(
    subject: str,
    node: str,
    status: str,
    detail: str = "",
    latency: float | None = None,
    threshold: float | None = None,
) -> None:
    if latency is None:
        latency_text = ""
    elif threshold is None:
        latency_text = f"latency {latency:6.2f}s (document total)"
    else:
        latency_text = f"latency {latency:6.2f}s (threshold {threshold:5.1f}s)"
    print(
        f"{time.strftime('%H:%M:%S')} | {subject:<8} | {node:<8} | "
        f"{status:<14} | {latency_text:<34} | {detail}"
    )


class _ConsoleHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        emit("system", "log", record.levelname, self.format(record))


def install(level: int = logging.WARNING) -> None:
    handler = _ConsoleHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.basicConfig(level=level, handlers=[handler])
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
