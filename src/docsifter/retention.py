"""Retention for review history, monitor logs, and generated report files.

Every webhook event writes monitor log rows, every review writes a history row,
and every review leaves an HTML report on disk. None of that was ever removed,
so a long-lived deployment grew without bound. This module applies one age
policy across all three and is run once at web startup.
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .runtime import get_data_dir, utcnow

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 90


def _cutoff(days: int) -> datetime:
    return utcnow() - timedelta(days=days)


def _delete_files(paths: Iterable[str]) -> int:
    removed = 0
    for path in paths:
        if not path:
            continue
        try:
            os.remove(path)
            removed += 1
        except FileNotFoundError:
            continue
        except OSError as e:
            logger.warning("Could not remove report %s: %s", path, e)
    return removed


def purge_orphan_reports(days: int, keep: Iterable[str]) -> int:
    """Remove report files older than the cutoff that nothing still references.

    Reports are also written for runs whose history row was never created (a
    failed startup, a cancelled task), so age alone has to cover them.
    """
    reports_dir = get_data_dir() / "reports"
    if not reports_dir.is_dir():
        return 0

    keep_resolved = {str(Path(path).resolve()) for path in keep if path}
    cutoff_timestamp = _cutoff(days).timestamp()
    removed = 0

    for report in reports_dir.glob("*.html"):
        if str(report.resolve()) in keep_resolved:
            continue
        try:
            if report.stat().st_mtime >= cutoff_timestamp:
                continue
            report.unlink()
            removed += 1
        except OSError as e:
            logger.warning("Could not remove report %s: %s", report, e)

    return removed


def purge_expired_data(history_manager: Any, days: int | None = None) -> Dict[str, int]:
    """Apply the retention policy. A non-positive ``days`` keeps everything."""
    days = DEFAULT_RETENTION_DAYS if days is None else int(days)
    summary = {"tasks": 0, "reviews": 0, "monitor_logs": 0, "report_files": 0}
    if days <= 0:
        return summary

    expired_reports: List[str] = []

    try:
        removed_tasks, task_reports = history_manager.purge_tasks_older_than(days)
        summary["tasks"] = removed_tasks
        expired_reports.extend(task_reports)
    except Exception as e:
        logger.warning("Local task retention skipped: %s", e)

    try:
        from . import models

        reviews, monitor_logs, review_reports = models.purge_github_history_older_than(days)
        summary["reviews"] = reviews
        summary["monitor_logs"] = monitor_logs
        expired_reports.extend(review_reports)
    except Exception as e:
        logger.warning("GitHub history retention skipped: %s", e)

    summary["report_files"] = _delete_files(expired_reports)

    try:
        kept = history_manager.all_report_paths()
    except Exception:
        kept = []
    summary["report_files"] += purge_orphan_reports(days, kept)

    if any(summary.values()):
        logger.info(
            "Retention (%s days): removed %s task(s), %s review(s), %s log row(s), %s report file(s)",
            days,
            summary["tasks"],
            summary["reviews"],
            summary["monitor_logs"],
            summary["report_files"],
        )
    return summary
