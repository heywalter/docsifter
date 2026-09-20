"""Tests for structured logging and in-process metrics (docsifter.observability)."""

import json
import logging

from docsifter import observability
from docsifter.observability import Metrics, configure_logging


def make_metrics() -> Metrics:
    return Metrics()


def test_counters_and_durations_snapshot():
    m = make_metrics()
    m.incr("reviews_total")
    m.incr("reviews_total")
    m.incr("files_total", 7)
    m.observe_duration("review_duration_seconds", 1.5)
    m.observe_duration("review_duration_seconds", 0.5)
    snap = m.snapshot()
    assert snap["reviews_total"] == 2
    assert snap["files_total"] == 7
    assert snap["review_duration_seconds_count"] == 2
    assert snap["review_duration_seconds_sum"] == 2.0


def test_prometheus_render_uses_expected_types():
    m = make_metrics()
    m.incr("docsifter_reviews_total", 3)
    m.observe_duration("docsifter_review_duration_seconds", 2.0)
    text = m.render_prometheus()
    assert "# TYPE docsifter_reviews_total counter" in text
    assert "docsifter_reviews_total 3" in text
    assert "# TYPE docsifter_review_duration_seconds_count_total counter" in text or (
        "# TYPE docsifter_review_duration_seconds_count counter" in text
    )
    assert "docsifter_review_duration_seconds_sum 2.0" in text


def test_record_review_updates_registry():
    before = observability.METRICS.snapshot()
    observability.record_review({"total_files": 4, "valid_changes": 9}, 1.25)
    after = observability.METRICS.snapshot()
    assert after["docsifter_files_total"] == before.get("docsifter_files_total", 0) + 4
    assert after["docsifter_findings_total"] == before.get("docsifter_findings_total", 0) + 9
    assert after["docsifter_review_duration_seconds_count"] == (
        before.get("docsifter_review_duration_seconds_count", 0) + 1
    )


def test_json_formatter_emits_parseable_single_line():
    formatter = observability.JsonLogFormatter()
    record = logging.LogRecord(
        name="docsifter.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="review completed files=%s",
        args=(3,),
        exc_info=None,
    )
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "WARNING"
    assert parsed["logger"] == "docsifter.test"
    assert parsed["message"] == "review completed files=3"


def test_configure_logging_respects_env(monkeypatch):
    monkeypatch.setenv("DOCSIFTER_LOG_FORMAT", "json")
    monkeypatch.setenv("DOCSIFTER_LOG_LEVEL", "DEBUG")
    configure_logging()
    root = logging.getLogger()
    try:
        assert root.level == logging.DEBUG
        assert isinstance(root.handlers[0].formatter, observability.JsonLogFormatter)
    finally:
        # Restore a plain-text default so other tests keep quiet handlers.
        monkeypatch.setenv("DOCSIFTER_LOG_FORMAT", "text")
        monkeypatch.setenv("DOCSIFTER_LOG_LEVEL", "INFO")
        configure_logging()


def test_web_metrics_endpoint_serves_prometheus_text():
    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    client = create_flask_app(DocumentReviewer(server_mode=True)).test_client()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    body = response.get_data(as_text=True)
    assert "docsifter_" in body
