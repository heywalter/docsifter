"""Routes that start, cancel, and report on a review run."""

import logging
import threading

from flask import jsonify, render_template, request

from ..corrector import DEFAULT_MODEL
from ..email_notification import get_email_service
from ..history_manager import TaskStatus
from ..orchestrator import is_model_allowed
from ..runtime import resolve_allowed_path
from .errors import api_error, server_error

logger = logging.getLogger(__name__)


def register_review_routes(app, reviewer) -> None:
    """Attach the review lifecycle routes to ``app``."""

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/cancel_task", methods=["POST"])
    def cancel_task():
        try:
            data = request.get_json(silent=True) or {}
            task_id = data.get("task_id")

            if not task_id:
                return api_error("Missing task_id", 400)

            cancelled = reviewer.history_manager.cancel_task(task_id)
            if not cancelled:
                cancelled = reviewer.github_task_manager.cancel_task(task_id)
            if not cancelled:
                return api_error("Task not found or no longer cancellable", 409)

            return jsonify({"success": True, "message": "Task cancelled"})

        except Exception as e:
            return server_error("cancel task", e)

    @app.route("/api/process", methods=["POST"])
    def process_directory_api():
        try:
            data = request.get_json(silent=True) or {}
            directory = data.get("directory", ".")
            debug = data.get("debug", False)
            auto_generate = data.get("auto_generate", True)
            model = data.get("model", "rule-based")

            if not is_model_allowed(reviewer.text_corrector, model):
                return api_error("Unsupported review model", 400)

            try:
                resolved_directory = resolve_allowed_path(directory)
            except PermissionError as e:
                # Raised with a message naming the requested path, which the
                # caller supplied, so it is safe to echo back.
                return api_error(str(e), 403)

            if not resolved_directory.exists() or not resolved_directory.is_dir():
                return api_error(f"Directory not found: {directory}", 400)

            directory = str(resolved_directory)
            task_id = reviewer.history_manager.create_task(directory, debug, auto_generate)

            thread = threading.Thread(
                target=_run_review,
                args=(reviewer, task_id, directory, debug, model, auto_generate),
                daemon=True,
            )
            thread.start()

            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Review task started",
                        "data": {"task_id": task_id},
                    }
                ),
                202,
            )

        except Exception as e:
            return server_error("start review", e)

    @app.route("/api/model/status", methods=["GET"])
    def get_model_status():
        try:
            with reviewer.review_lock:
                model_info = reviewer.get_model_info()
                current_model = getattr(reviewer.text_corrector, "current_model", DEFAULT_MODEL)
                if not reviewer.text_corrector.ai_correction_enabled:
                    current_model = "rule-based"
            return jsonify(
                {
                    "success": True,
                    "data": {
                        "current_model": current_model,
                        "model_info": model_info,
                        "ai_correction_enabled": reviewer.text_corrector.ai_correction_enabled,
                        "model_loaded": bool(reviewer.text_corrector.gpt_client),
                        "model_error": reviewer.text_corrector.model_error,
                    },
                }
            )
        except Exception as e:
            return server_error("read model status", e)


def _run_review(reviewer, task_id, directory, debug, model, auto_generate) -> None:
    """Run one review to completion in a worker thread.

    Everything worth reading afterwards is written to the task's own log through
    ``history_manager``, because the Web UI shows that log and the process
    logger is not visible from the browser.
    """
    try:
        result = reviewer.run_local_review(
            directory,
            debug=debug,
            task_id=task_id,
            model=model,
            auto_generate=auto_generate,
        )

        if result.get("cancelled"):
            return

        if reviewer.history_manager.is_task_cancelled(task_id):
            return

        reviewer.history_manager.update_task_status(task_id, TaskStatus.COMPLETED)

        if auto_generate:
            _notify_completion(reviewer, task_id, result)

    except Exception as e:
        if not reviewer.history_manager.is_task_cancelled(task_id):
            reviewer.history_manager.update_task_status(task_id, TaskStatus.FAILED, str(e))
            reviewer.history_manager.add_log(task_id, "ERROR", f"Processing failed: {str(e)}")
            logger.exception("review task failed task_id=%s", task_id)
            _notify_failure(reviewer, task_id, e)


def _notify_completion(reviewer, task_id, result) -> None:
    """Send the completion email, if one is configured and asked for."""
    try:
        email_service = get_email_service(reviewer.config_manager)
        email_config = email_service.get_config()
        should_notify = (
            email_service.is_enabled
            and email_service.is_configured()
            and email_config.get("notify_on_local_complete", True)
        )

        if should_notify and result.get("report_path"):
            task_info = reviewer.history_manager.get_task_detail(task_id)
            email_result = email_service.send_report_notification(
                task_id, result["report_path"], result["stats"], task_info
            )
            reviewer.history_manager.add_log(
                task_id,
                "INFO",
                f"Email notification: {email_result.get('message')}",
            )
        else:
            reviewer.history_manager.add_log(
                task_id,
                "INFO",
                "Email notification disabled or not configured",
            )
    except Exception as e:
        reviewer.history_manager.add_log(task_id, "ERROR", f"Email notification failed: {str(e)}")


def _notify_failure(reviewer, task_id, error) -> None:
    """Send the failure email. A broken mailer must not mask the real failure."""
    try:
        email_service = get_email_service(reviewer.config_manager)
        email_result = email_service.send_error_notification(
            task_id,
            str(error),
            reviewer.history_manager.get_task_detail(task_id) or {},
        )
        reviewer.history_manager.add_log(
            task_id,
            "INFO" if email_result.get("success") else "ERROR",
            f"Error email notification: {email_result.get('message')}",
        )
    except Exception as notification_error:
        reviewer.history_manager.add_log(
            task_id,
            "ERROR",
            f"Error email notification failed: {notification_error}",
        )
