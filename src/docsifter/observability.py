"""Structured logging and lightweight in-process metrics.

Logging:
    Call :func:`configure_logging` once at entry point startup (CLI and web).
    ``DOCSIFTER_LOG_FORMAT=json`` switches every log line to a single-line JSON
    object; ``DOCSIFTER_LOG_LEVEL`` accepts the usual level names.

Metrics:
    :data:`METRICS` is a process-global counter registry. Multi-replica
    deployments each keep their own view by design (see README deployment
    topology); scrapers can poll ``GET /metrics`` for Prometheus text.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone

# --- Structured logging -------------------------------------------------------


class JsonLogFormatter(logging.Formatter):
    """Render each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_format: str = None, level: str = None) -> None:
    """Install the root handler. Defaults come from DOCSIFTER_LOG_* env vars."""
    chosen_format = (log_format or os.environ.get("DOCSIFTER_LOG_FORMAT") or "text").lower()
    chosen_level = (level or os.environ.get("DOCSIFTER_LOG_LEVEL") or "INFO").upper()
    resolved_level = getattr(logging, chosen_level, logging.INFO)

    handler = logging.StreamHandler()
    if chosen_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)


# --- Metrics ------------------------------------------------------------------


class Metrics:
    """Thread-safe counters and duration accumulators."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict = {}
        self._durations: dict = {}  # name -> [count, total_seconds]

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe_duration(self, name: str, seconds: float) -> None:
        with self._lock:
            count, total = self._durations.get(name, (0, 0.0))
            self._durations[name] = (count + 1, total + seconds)

    def snapshot(self) -> dict:
        with self._lock:
            data = dict(self._counters)
            for name, (count, total) in self._durations.items():
                data[f"{name}_count"] = count
                data[f"{name}_sum"] = round(total, 3)
            return data

    def render_prometheus(self) -> str:
        lines = []
        for name, value in sorted(self.snapshot().items()):
            if name.endswith("_sum"):
                metric, metric_type = name, "gauge"
            else:
                metric = name if name.endswith("_total") else f"{name}_total"
                metric_type = "counter"
            lines.append(f"# TYPE {metric} {metric_type}")
            lines.append(f"{metric} {value}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()


def record_review(stats: dict, duration_seconds: float, cancelled: bool = False) -> None:
    """Feed one completed review run into the global metrics registry."""
    if cancelled:
        METRICS.incr("docsifter_reviews_cancelled_total")
    else:
        METRICS.incr("docsifter_reviews_total")
    METRICS.incr("docsifter_files_total", int(stats.get("total_files", 0)))
    METRICS.incr("docsifter_findings_total", int(stats.get("valid_changes", 0)))
    METRICS.observe_duration("docsifter_review_duration_seconds", duration_seconds)
