"""Retention of review history, monitor logs, and generated reports."""

from datetime import datetime, timedelta
from pathlib import Path


def _aged_report(reports_dir: Path, name: str, days_old: int) -> Path:
    report = reports_dir / name
    report.write_text("<html>report</html>", encoding="utf-8")
    old = (datetime.now() - timedelta(days=days_old)).timestamp()
    import os

    os.utime(report, (old, old))
    return report


def test_retention_removes_old_tasks_logs_and_their_reports(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.history_manager import HistoryManager, TaskStatus
    from docsifter.retention import purge_expired_data

    manager = HistoryManager()
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    old_report = _aged_report(reports_dir, "old.html", 200)
    fresh_report = _aged_report(reports_dir, "fresh.html", 1)

    old_task = manager.create_task("/docs", auto_generate=False)
    fresh_task = manager.create_task("/docs", auto_generate=False)
    manager.set_report_path(old_task, str(old_report))
    manager.set_report_path(fresh_task, str(fresh_report))
    manager.update_task_status(old_task, TaskStatus.COMPLETED)
    manager.update_task_status(fresh_task, TaskStatus.COMPLETED)
    manager.add_log(old_task, "INFO", "old log line")

    # Age the first task past the window.
    import sqlite3

    stale = (datetime.now() - timedelta(days=200)).isoformat()
    with sqlite3.connect(manager.db_path) as conn:
        conn.execute("UPDATE task_history SET created_at = ? WHERE id = ?", (stale, old_task))
        conn.commit()

    summary = purge_expired_data(manager, days=90)

    assert summary["tasks"] == 1
    assert manager.get_task_detail(old_task) is None
    assert manager.get_task_detail(fresh_task) is not None
    assert not old_report.exists()
    assert fresh_report.exists()

    # Child rows must go with the parent rather than being orphaned.
    with sqlite3.connect(manager.db_path) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM task_logs WHERE task_id = ?", (old_task,)
        ).fetchone()[0]
    assert remaining == 0


def test_retention_removes_orphaned_report_files(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.history_manager import HistoryManager
    from docsifter.retention import purge_expired_data

    manager = HistoryManager()
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # A report whose run never produced a history row: age alone must cover it.
    orphan = _aged_report(reports_dir, "orphan.html", 200)
    recent_orphan = _aged_report(reports_dir, "recent.html", 2)

    purge_expired_data(manager, days=90)

    assert not orphan.exists()
    assert recent_orphan.exists()


def test_retention_keeps_a_referenced_report_regardless_of_file_age(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.history_manager import HistoryManager
    from docsifter.retention import purge_expired_data

    manager = HistoryManager()
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # The file is old but its task is inside the window, so it must survive.
    report = _aged_report(reports_dir, "referenced.html", 200)
    task_id = manager.create_task("/docs", auto_generate=False)
    manager.set_report_path(task_id, str(report))

    purge_expired_data(manager, days=90)

    assert report.exists()
    assert manager.get_task_detail(task_id) is not None


def test_retention_disabled_keeps_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.history_manager import HistoryManager
    from docsifter.retention import purge_expired_data

    manager = HistoryManager()
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ancient = _aged_report(reports_dir, "ancient.html", 5000)

    summary = purge_expired_data(manager, days=0)

    assert summary == {"tasks": 0, "reviews": 0, "monitor_logs": 0, "report_files": 0}
    assert ancient.exists()


def test_retention_removes_old_github_reviews_and_monitor_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter import models
    from docsifter.history_manager import HistoryManager
    from docsifter.retention import purge_expired_data

    models.init_db()
    manager = HistoryManager()
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    old_report = _aged_report(reports_dir, "gh-old.html", 200)

    stale = models.utcnow() - timedelta(days=200)
    with models.get_session() as session:
        session.add(
            models.GitHubReviewHistory(
                repo_url="https://github.com/acme/docs",
                pr_number=1,
                status="completed",
                started_at=stale,
                report_path=str(old_report),
            )
        )
        session.add(
            models.GitHubReviewHistory(
                repo_url="https://github.com/acme/docs", pr_number=2, status="completed"
            )
        )
        session.add(models.GitHubMonitorLog(status="info", message="old", timestamp=stale))
        session.add(models.GitHubMonitorLog(status="info", message="fresh"))

    summary = purge_expired_data(manager, days=90)

    assert summary["reviews"] == 1
    assert summary["monitor_logs"] == 1
    assert not old_report.exists()
    with models.get_session() as session:
        assert session.query(models.GitHubReviewHistory).count() == 1
        assert session.query(models.GitHubMonitorLog).count() == 1


# --- timestamp consistency ------------------------------------------------------


def test_both_histories_record_the_same_moment(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from datetime import datetime

    from docsifter import models
    from docsifter.history_manager import HistoryManager

    models.init_db()
    manager = HistoryManager()

    with models.get_session() as session:
        session.add(models.GitHubReviewHistory(repo_url="r", pr_number=1, status="completed"))
    with models.get_session() as session:
        review = session.query(models.GitHubReviewHistory).first().to_dict()
    task = manager.get_task_detail(manager.create_task("/docs", auto_generate=False))

    # Review history was stored in UTC while local tasks used local time, so the
    # same moment was recorded hours apart and shown that way in the UI.
    reviewed_at = datetime.fromisoformat(review["started_at"])
    started_at = datetime.fromisoformat(task["start_time"])
    assert abs((reviewed_at - started_at).total_seconds()) < 60


def test_serialized_timestamps_carry_an_explicit_offset(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from datetime import datetime

    from docsifter import models
    from docsifter.history_manager import HistoryManager, TaskStatus

    models.init_db()
    manager = HistoryManager()
    task_id = manager.create_task("/docs", auto_generate=False)
    manager.add_log(task_id, "INFO", "line")
    manager.update_task_status(task_id, TaskStatus.COMPLETED)

    with models.get_session() as session:
        session.add(models.GitHubMonitorLog(status="info", message="m"))
    with models.get_session() as session:
        log = session.query(models.GitHubMonitorLog).first().to_dict()

    detail = manager.get_task_detail(task_id)
    history = manager.get_task_history(limit=1)[0]

    # An offset-free timestamp is parsed as local time by any client.
    for value in (
        detail["start_time"],
        detail["created_at"],
        detail["logs"][0]["timestamp"],
        history["start_time"],
        log["timestamp"],
    ):
        assert datetime.fromisoformat(value).tzinfo is not None, value


def test_isoformat_utc_leaves_an_aware_value_alone():
    from datetime import datetime, timedelta, timezone

    from docsifter.runtime import isoformat_utc

    aware = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    assert isoformat_utc(aware) == aware.isoformat()
    assert isoformat_utc(None) is None
    assert isoformat_utc("not a timestamp") == "not a timestamp"
