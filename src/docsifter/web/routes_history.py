"""Routes that read review history, reports, dashboard state, and metrics."""

import logging
import os

from flask import abort, jsonify, request, send_file

from ..observability import METRICS
from ..runtime import get_runtime_path
from .errors import api_error, server_error

logger = logging.getLogger(__name__)

MAX_HISTORY_PAGE_SIZE = 100


def register_history_routes(app, reviewer) -> None:
    """Attach the history, report, and metrics routes to ``app``."""

    @app.route("/api/history", methods=["GET"])
    def get_task_history():
        try:
            page = max(1, int(request.args.get("page", 1)))
            page_size = min(MAX_HISTORY_PAGE_SIZE, max(1, int(request.args.get("page_size", 10))))

            offset = (page - 1) * page_size
            history = reviewer.history_manager.get_task_history(page_size, offset)
            total_count = reviewer.history_manager.get_task_count()
            total_pages = max(1, (total_count + page_size - 1) // page_size)

            return jsonify(
                {
                    "success": True,
                    "data": {
                        "tasks": history,
                        "pagination": {
                            "current_page": page,
                            "page_size": page_size,
                            "total_pages": total_pages,
                            "total_count": total_count,
                        },
                    },
                }
            )
        except Exception as e:
            return server_error("read task history", e)

    @app.route("/api/history/<task_id>", methods=["GET"])
    def get_task_details(task_id):
        try:
            details = reviewer.history_manager.get_task_detail(task_id)
            if details:
                return jsonify({"success": True, "data": details})
            return api_error("Task not found", 404)
        except Exception as e:
            return server_error("read task detail", e)

    @app.route("/api/history/<task_id>/logs", methods=["GET"])
    def get_task_logs(task_id):
        try:
            logs = reviewer.history_manager.get_task_logs(task_id)
            return jsonify({"success": True, "data": logs})
        except Exception as e:
            return server_error("read task logs", e)

    @app.route("/api/history/<task_id>/progress", methods=["GET"])
    def get_task_progress(task_id):
        try:
            progress = reviewer.history_manager.get_task_progress(task_id)
            return jsonify({"success": True, "data": progress})
        except Exception as e:
            return server_error("read task progress", e)

    @app.route("/api/history/<task_id>/download", methods=["GET"])
    def download_task_report(task_id):
        try:
            details = reviewer.history_manager.get_task_detail(task_id)
            if not details or not details.get("report_path"):
                return api_error("Report file not found", 404)

            report_path = details["report_path"]
            if not os.path.exists(report_path):
                return api_error("Report file has been deleted", 404)

            return send_file(
                report_path, as_attachment=True, download_name=f"report_{task_id}.html"
            )
        except Exception as e:
            return server_error("download report", e)

    @app.route("/api/history/<task_id>", methods=["DELETE"])
    def delete_task(task_id):
        try:
            if reviewer.history_manager.delete_task(task_id):
                return jsonify({"success": True, "message": "Task deleted"})
            return api_error("Task not found", 404)
        except Exception as e:
            return server_error("delete task", e)

    @app.route("/api/dashboard/status", methods=["GET"])
    def get_dashboard_status():
        try:
            running_tasks = reviewer.history_manager.get_running_tasks()
            recent_stats = reviewer.history_manager.get_recent_stats()

            return jsonify(
                {
                    "success": True,
                    "data": {
                        "running_tasks_count": len(running_tasks),
                        "running_tasks": running_tasks,
                        "recent_stats": recent_stats,
                    },
                }
            )
        except Exception as e:
            return server_error("read dashboard status", e)

    @app.route("/report.html")
    def serve_report():
        report_path = reviewer.history_manager.get_latest_report_path()
        if not report_path or not os.path.exists(report_path):
            abort(404)
        return send_file(report_path)

    @app.route("/report_full_<task_id>.html")
    def serve_full_report(task_id):
        report_path = get_runtime_path("reports", f"local-{task_id}-full.html")
        if not os.path.exists(report_path):
            abort(404)
        return send_file(report_path)

    @app.route("/stats")
    def get_stats():
        try:
            return jsonify(reviewer.history_manager.get_total_stats())
        except Exception:
            # The lifetime aggregate is a nicety; the recent window is enough to
            # keep the dashboard populated when it cannot be computed.
            logger.warning("total stats unavailable, falling back to the recent window")
            return jsonify(reviewer.history_manager.get_recent_stats())

    @app.route("/api/current-stats")
    def get_current_stats():
        return jsonify(reviewer.history_manager.get_recent_stats())

    @app.route("/metrics")
    def get_metrics():
        return (
            METRICS.render_prometheus(),
            200,
            {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
        )
