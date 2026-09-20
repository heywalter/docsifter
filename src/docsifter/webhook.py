"""GitHub webhook monitoring routes for the DocSifter web app."""

import hashlib
import hmac
import os
import secrets
import threading

from flask import jsonify, request, send_from_directory
from sqlalchemy.exc import IntegrityError

from .email_notification import get_email_service
from .orchestrator import is_model_allowed
from .runtime import utcnow


def _get_models_module():
    """Import the ORM layer lazily: the local review path never needs it."""
    from . import models

    return models


def register_github_routes(app, reviewer) -> None:
    """Attach GitHub webhook monitoring endpoints to the Flask app."""

    def _get_or_create_github_monitor_config():
        """Return the monitor row as a dict, creating it on first use."""
        models = _get_models_module()

        with models.get_session() as session:
            config = session.query(models.GitHubMonitorConfig).first()
            if not config:
                config = models.GitHubMonitorConfig(
                    monitor_events=["pr_created", "pr_updated", "pr_reopened"],
                    is_running=False,
                    webhook_enabled=False,
                )
                session.add(config)
                session.commit()
            return config.to_dict()

    def _update_github_monitor_config(updates: dict):
        """Apply a partial update to the monitor row."""
        models = _get_models_module()

        with models.get_session() as session:
            config = session.query(models.GitHubMonitorConfig).first()
            if not config:
                config = models.GitHubMonitorConfig()
                session.add(config)

            for key, value in updates.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            session.commit()
            return config.to_dict()

    def _normalize_repo_url(repo_url: str) -> str:
        """Reduce a repository URL to its canonical https form for comparison."""
        if not repo_url:
            return ""
        url = repo_url.strip()
        if url.endswith(".git"):
            url = url[:-4]
        return url.rstrip("/")

    def _get_webhook_url() -> str:
        """The URL to hand GitHub, preferring DOCSIFTER_PUBLIC_URL when set."""
        public_url = os.getenv("DOCSIFTER_PUBLIC_URL", "").strip().rstrip("/")
        if public_url:
            return f"{public_url}/api/github/webhook"
        root = request.url_root.rstrip("/")
        return f"{root}/api/github/webhook"

    def _ensure_webhook_secret():
        """Return the shared secret, generating one the first time it is asked for."""
        models = _get_models_module()

        with models.get_session() as session:
            config = session.query(models.GitHubMonitorConfig).first()
            created = False
            if not config:
                config = models.GitHubMonitorConfig()
                session.add(config)
                session.commit()
            if not config.webhook_secret:
                config.webhook_secret = secrets.token_hex(32)
                created = True
                session.commit()
            return config.webhook_secret, created

    def _verify_github_signature(raw_body: bytes, secret: str) -> bool:
        """Check GitHub's HMAC over the raw body.

        Prefers the SHA-256 header and falls back to the legacy SHA-1 one.
        Both comparisons use :func:`hmac.compare_digest`, and an unsigned
        request is rejected -- this endpoint is deliberately reachable
        without the administrator token, so the signature is all that stands
        between a stranger and a review run.
        """
        sig256 = request.headers.get("X-Hub-Signature-256", "")
        if sig256.startswith("sha256="):
            their = sig256.split("=", 1)[1]
            ours = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(their, ours)

        sig1 = request.headers.get("X-Hub-Signature", "")
        if sig1.startswith("sha1="):
            their = sig1.split("=", 1)[1]
            ours = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha1).hexdigest()
            return hmac.compare_digest(their, ours)

        return False

    def _create_review_history(
        repo_url: str,
        pr_info: dict,
        trigger_type: str,
        delivery_id: str = None,
    ):
        """Claim one pull request review, returning ``(history_id, created)``.

        The uniqueness constraint on delivery id and head revision is what
        makes this the de-duplication point: a redelivery of the same event,
        or a second webhook for a commit already under review, gets
        ``created=False`` and no second run.
        """
        models = _get_models_module()

        try:
            head_sha = (pr_info.get("head") or {}).get("sha")

            with models.get_session() as session:
                existing = None
                if delivery_id:
                    # GitHub reuses the delivery id when it retries a delivery.
                    existing = (
                        session.query(models.GitHubReviewHistory)
                        .filter(models.GitHubReviewHistory.delivery_id == delivery_id)
                        .first()
                    )

                if not existing:
                    # One push commonly raises several events (synchronize plus
                    # edited, say) with different delivery ids. Those describe the
                    # same commit, so collapse them onto the in-flight review
                    # instead of cloning and reviewing the same tree twice.
                    in_flight = session.query(models.GitHubReviewHistory).filter(
                        models.GitHubReviewHistory.repo_url == repo_url,
                        models.GitHubReviewHistory.pr_number == pr_info.get("number"),
                        models.GitHubReviewHistory.status.in_(["pending", "processing"]),
                    )
                    if head_sha:
                        in_flight = in_flight.filter(
                            models.GitHubReviewHistory.head_sha == head_sha
                        )
                    existing = in_flight.first()

                if existing:
                    return existing.id, False

                history = models.GitHubReviewHistory(
                    repo_url=repo_url,
                    pr_number=pr_info.get("number"),
                    pr_title=pr_info.get("title"),
                    pr_url=pr_info.get("html_url"),
                    trigger_type=trigger_type,
                    delivery_id=delivery_id,
                    head_sha=head_sha,
                    status="pending",
                )
                session.add(history)
                session.flush()
                return history.id, True
        except IntegrityError:
            if not delivery_id:
                raise
            with models.get_session() as session:
                existing = (
                    session.query(models.GitHubReviewHistory)
                    .filter(models.GitHubReviewHistory.delivery_id == delivery_id)
                    .one()
                )
                return existing.id, False

    def _update_review_history(history_id: int, updates: dict):
        """Apply a partial update to one review-history row."""
        models = _get_models_module()

        with models.get_session() as session:
            history = session.query(models.GitHubReviewHistory).filter_by(id=history_id).first()
            if not history:
                return
            for key, value in updates.items():
                if hasattr(history, key):
                    setattr(history, key, value)
            if updates.get("status") in {"completed", "failed", "cancelled"}:
                history.completed_at = utcnow()
            session.commit()

    def _add_monitor_log(status: str, message: str, details=None):
        """Append one line to the monitor log the Web UI displays."""
        models = _get_models_module()

        with models.get_session() as session:
            session.add(models.GitHubMonitorLog(status=status, message=message, details=details))
            session.commit()

    @app.route("/api/github/webhook/status", methods=["GET"])
    def get_github_webhook_status():
        """Report the monitor configuration, without returning the secret."""
        try:
            config = _get_or_create_github_monitor_config()
            config["repo_url"] = _normalize_repo_url(config.get("repo_url"))
            return jsonify(
                {
                    "success": True,
                    "data": {**config, "webhook_url": _get_webhook_url()},
                }
            )
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/webhook/config", methods=["POST"])
    def save_github_webhook_config():
        """Update the watched repository and the event filter."""
        try:
            data = request.get_json() or {}
            repo_url = _normalize_repo_url(data.get("repo_url", ""))
            monitor_events = data.get("monitor_events", [])
            auto_review_enabled = data.get("auto_review_enabled", True)
            only_changed_files = data.get("only_changed_files", True)
            email_notification_enabled = data.get("email_notification_enabled", True)
            review_model = data.get("review_model", "rule-based")

            if not repo_url:
                return jsonify({"success": False, "message": "GitHub repository URL is required"})
            if not repo_url.startswith("https://github.com/"):
                return jsonify(
                    {"success": False, "message": "Please enter a valid GitHub repository URL"}
                )
            if not is_model_allowed(reviewer.text_corrector, review_model):
                return jsonify({"success": False, "message": "Unsupported review model"}), 400

            _update_github_monitor_config(
                {
                    "repo_url": repo_url,
                    "monitor_events": monitor_events,
                    "auto_review_enabled": auto_review_enabled,
                    "only_changed_files": only_changed_files,
                    "email_notification_enabled": email_notification_enabled,
                    "review_model": review_model,
                }
            )

            secret, created = _ensure_webhook_secret()

            response_data = {
                "webhook_url": _get_webhook_url(),
                "webhook_secret_configured": True,
            }
            if created:
                response_data["webhook_secret"] = secret
            return jsonify(
                {
                    "success": True,
                    "message": "Webhook monitoring config saved",
                    "data": response_data,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/webhook/secret/regenerate", methods=["POST"])
    def regenerate_github_webhook_secret():
        """Roll the shared secret. Deliveries signed with the old one stop verifying."""
        try:
            new_secret = secrets.token_hex(32)
            _update_github_monitor_config({"webhook_secret": new_secret})
            _add_monitor_log("info", "Webhook secret regenerated")
            return jsonify({"success": True, "data": {"webhook_secret": new_secret}})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/webhook/enable", methods=["POST"])
    def enable_github_webhook_monitoring():
        """Start accepting deliveries for the configured repository."""
        try:
            config = _get_or_create_github_monitor_config()
            repo_url = _normalize_repo_url(config.get("repo_url"))
            if not repo_url:
                return jsonify({"success": False, "message": "Please save repository config first"})

            secret, created = _ensure_webhook_secret()
            _update_github_monitor_config({"webhook_enabled": True, "is_running": True})
            _add_monitor_log("success", "Webhook monitoring enabled", f"repo: {repo_url}")

            response_data = {
                "repo_url": repo_url,
                "webhook_url": _get_webhook_url(),
                "webhook_secret_configured": True,
            }
            if created:
                response_data["webhook_secret"] = secret
            return jsonify(
                {
                    "success": True,
                    "message": "Webhook monitoring enabled",
                    "data": response_data,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/webhook/disable", methods=["POST"])
    def disable_github_webhook_monitoring():
        """Stop accepting deliveries; configuration and history are kept."""
        try:
            config = _get_or_create_github_monitor_config()
            repo_url = _normalize_repo_url(config.get("repo_url"))
            _update_github_monitor_config({"webhook_enabled": False, "is_running": False})
            _add_monitor_log(
                "success", "Webhook monitoring disabled", f"repo: {repo_url or 'not set'}"
            )
            return jsonify({"success": True, "message": "Webhook monitoring disabled"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/webhook", methods=["POST"])
    def github_webhook():
        """Receive one delivery from GitHub and queue a review if it qualifies.

        The handler answers quickly and does the review on a worker thread,
        because GitHub times a delivery out. It filters in four stages --
        signature, event type, pull-request action, and the operator's event
        selection -- and de-duplicates on the delivery id and head revision,
        so a redelivery or a repeated push does not review the same commit
        twice.
        """
        history_id = None
        accepted = False
        try:
            config = _get_or_create_github_monitor_config()
            if not config.get("webhook_enabled"):
                return jsonify({"success": True, "message": "Webhook not enabled"}), 200

            secret, _ = _ensure_webhook_secret()
            raw = request.get_data(cache=True) or b""
            if not _verify_github_signature(raw, secret):
                _add_monitor_log("warning", "Webhook signature verification failed")
                return jsonify({"success": False, "message": "signature mismatch"}), 401

            event = request.headers.get("X-GitHub-Event", "")
            payload = request.get_json(silent=True) or {}

            if event == "ping":
                _add_monitor_log("info", "Webhook ping")
                return jsonify({"success": True, "message": "pong"})

            if event != "pull_request":
                return jsonify({"success": True, "message": "ignored"}), 200

            action = payload.get("action")
            delivery_id = request.headers.get("X-GitHub-Delivery")
            action_to_monitor_event = {
                "opened": "pr_created",
                "reopened": "pr_reopened",
                "synchronize": "pr_updated",
                "edited": "pr_updated",
                "ready_for_review": "pr_updated",
            }
            monitor_event = action_to_monitor_event.get(action)
            if not monitor_event:
                return jsonify({"success": True, "message": "ignored"}), 200

            if config.get("monitor_events") and monitor_event not in (
                config.get("monitor_events") or []
            ):
                return jsonify({"success": True, "message": "ignored"}), 200

            pr = payload.get("pull_request") or {}
            repo = payload.get("repository") or {}

            configured_repo = _normalize_repo_url(config.get("repo_url"))
            incoming_repo = _normalize_repo_url(repo.get("html_url") or repo.get("clone_url") or "")
            if configured_repo and incoming_repo and configured_repo != incoming_repo:
                _add_monitor_log(
                    "warning",
                    "Webhook repository mismatch",
                    f"configured: {configured_repo}, incoming: {incoming_repo}",
                )
                return jsonify({"success": True, "message": "ignored"}), 200

            pr_number = pr.get("number")
            if not pr_number:
                return jsonify({"success": True, "message": "ignored"}), 200

            if not config.get("auto_review_enabled", True):
                _add_monitor_log("info", f"PR #{pr_number} triggered but auto-review is disabled")
                return jsonify({"success": True, "message": "disabled"}), 200

            _update_github_monitor_config({"last_check": utcnow()})
            history_id, created = _create_review_history(
                configured_repo or incoming_repo,
                pr,
                "webhook",
                delivery_id=delivery_id,
            )
            if not created:
                _add_monitor_log("info", f"PR #{pr_number} review already in progress")
                return jsonify(
                    {"success": True, "message": "already processing", "history_id": history_id}
                )
            _update_review_history(history_id, {"status": "processing"})
            _add_monitor_log("info", f"PR event received: {action}", f"PR #{pr_number}")

            task_id = reviewer.github_task_manager.create_github_task(
                configured_repo or incoming_repo,
                [],
                not config.get("only_changed_files", True),
                pr_number,
                ref=f"refs/pull/{pr_number}/head",
            )

            def execute_task():
                start = utcnow()
                try:
                    webhook_model = config.get("review_model") or "rule-based"
                    result = reviewer.run_github_review(task_id, webhook_model)
                    if result.get("cancelled"):
                        _update_review_history(
                            history_id,
                            {
                                "status": "cancelled",
                                "processing_time": int((utcnow() - start).total_seconds()),
                            },
                        )
                        _add_monitor_log("info", f"PR #{pr_number} auto-review cancelled")
                        return
                    total_files = result.get("total_files", 0)
                    files_with_issues = result.get("files_with_issues", 0)
                    stats = result.get("stats") or {}
                    corrections = stats.get("valid_changes", 0)
                    report_path = result.get("report_path")

                    elapsed = int((utcnow() - start).total_seconds())
                    email_sent = False
                    if config.get("email_notification_enabled", True) and report_path:
                        try:
                            email_service = get_email_service(reviewer.config_manager)
                            email_config = email_service.get_config()
                            should_notify = (
                                email_service.is_enabled
                                and email_service.is_configured()
                                and email_config.get("notify_on_github_complete", True)
                            )
                            if should_notify:
                                task_info = reviewer.github_task_manager.get_task_status(task_id)
                                email_result = email_service.send_report_notification(
                                    task_id, report_path, stats, task_info
                                )
                                email_sent = bool(email_result.get("success"))
                                _add_monitor_log(
                                    "success" if email_sent else "warning",
                                    f"PR #{pr_number} email notification",
                                    email_result.get("message"),
                                )
                            else:
                                _add_monitor_log(
                                    "info",
                                    f"PR #{pr_number} email notification disabled or not configured",
                                )
                        except Exception as e:
                            _add_monitor_log(
                                "error", f"PR #{pr_number} email notification failed", str(e)
                            )

                    _update_review_history(
                        history_id,
                        {
                            "status": "completed",
                            "files_processed": total_files,
                            "files_with_issues": files_with_issues,
                            "total_corrections": corrections,
                            "processing_time": elapsed,
                            "report_path": report_path,
                            "email_sent": email_sent,
                        },
                    )
                    _add_monitor_log(
                        "success",
                        f"PR #{pr_number} auto-review completed",
                        f"task: {task_id}, files: {total_files}, corrections: {corrections}",
                    )
                except Exception as e:
                    elapsed = int((utcnow() - start).total_seconds())
                    _update_review_history(
                        history_id,
                        {"status": "failed", "processing_time": elapsed, "error_message": str(e)},
                    )
                    _add_monitor_log("error", f"PR #{pr_number} auto-review failed", str(e))
                    if config.get("email_notification_enabled", True):
                        try:
                            email_service = get_email_service(reviewer.config_manager)
                            email_result = email_service.send_error_notification(
                                task_id,
                                str(e),
                                reviewer.github_task_manager.get_task_status(task_id),
                            )
                            _add_monitor_log(
                                "success" if email_result.get("success") else "warning",
                                f"PR #{pr_number} error notification",
                                email_result.get("message"),
                            )
                        except Exception as notification_error:
                            _add_monitor_log(
                                "error",
                                f"PR #{pr_number} error notification failed",
                                str(notification_error),
                            )

            thread = threading.Thread(target=execute_task, daemon=True)
            thread.start()
            accepted = True

            return jsonify(
                {
                    "success": True,
                    "message": "accepted",
                    "task_id": task_id,
                    "history_id": history_id,
                }
            )
        except Exception as e:
            if history_id is not None and not accepted:
                try:
                    _update_review_history(
                        history_id,
                        {
                            "status": "failed",
                            "error_message": f"Webhook acceptance failed: {e}",
                            "delivery_id": None,
                        },
                    )
                except Exception:
                    app.logger.exception("Failed to record webhook acceptance error")
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/api/github/webhook/logs", methods=["GET"])
    def get_github_webhook_logs():
        """Return recent monitor log lines for the Web UI."""
        try:
            models = _get_models_module()

            with models.get_session() as session:
                total_logs = session.query(models.GitHubMonitorLog).count()
                logs = (
                    session.query(models.GitHubMonitorLog)
                    .order_by(models.GitHubMonitorLog.timestamp.desc())
                    .limit(50)
                    .all()
                )
                logs_list = [log.to_dict() for log in logs]
                last_check = logs_list[0]["timestamp"] if logs_list else None

            return jsonify(
                {
                    "success": True,
                    "data": {
                        "logs": logs_list,
                        "last_check": last_check,
                        "total_logs": total_logs,
                        "returned_logs": len(logs_list),
                    },
                }
            )
        except Exception as e:
            app.logger.error(f"Failed to fetch webhook logs: {str(e)}")
            return jsonify(
                {
                    "success": False,
                    "message": f"Failed to fetch webhook logs: {str(e)}",
                    "data": {"logs": [], "last_check": None, "total_logs": 0},
                }
            )

    @app.route("/api/github/review-history", methods=["GET"])
    def get_github_review_history():
        """Return one page of past pull request reviews."""
        try:
            page = request.args.get("page", 1, type=int)
            limit = request.args.get("limit", 10, type=int)
            models = _get_models_module()

            with models.get_session() as session:
                offset = (page - 1) * limit
                total = session.query(models.GitHubReviewHistory).count()
                histories = (
                    session.query(models.GitHubReviewHistory)
                    .order_by(models.GitHubReviewHistory.started_at.desc())
                    .offset(offset)
                    .limit(limit)
                    .all()
                )

                return jsonify(
                    {
                        "success": True,
                        "data": [h.to_dict() for h in histories],
                        "pagination": {
                            "page": page,
                            "limit": limit,
                            "total": total,
                            "has_prev": page > 1,
                            "has_next": offset + limit < total,
                        },
                    }
                )
        except Exception as e:
            app.logger.error(f"Failed to fetch review history: {str(e)}")
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/review-history/stats", methods=["GET"])
    def get_github_review_statistics():
        """Return the aggregate counters shown on the monitoring panel."""
        try:
            models = _get_models_module()

            with models.get_session() as session:
                total_tasks = session.query(models.GitHubReviewHistory).count()
                completed_tasks = (
                    session.query(models.GitHubReviewHistory).filter_by(status="completed").count()
                )
                total_files = (
                    session.query(models.GitHubReviewHistory)
                    .with_entities(models.GitHubReviewHistory.files_processed)
                    .all()
                )
                total_files_count = sum(f[0] or 0 for f in total_files)

            return jsonify(
                {
                    "success": True,
                    "data": {
                        "total_tasks": total_tasks,
                        "total_files": total_files_count,
                        "completed_tasks": completed_tasks,
                        "success_rate": (completed_tasks / max(1, total_tasks)) * 100,
                    },
                }
            )
        except Exception as e:
            app.logger.error(f"Failed to fetch statistics: {str(e)}")
            return jsonify({"success": False, "message": str(e)})

    @app.route("/api/github/review-history/<int:history_id>/report", methods=["GET"])
    def download_review_report(history_id):
        """Serve the stored HTML report for one past pull request review."""
        try:
            models = _get_models_module()

            with models.get_session() as session:
                history = session.query(models.GitHubReviewHistory).filter_by(id=history_id).first()
                if not history or not history.report_path:
                    return jsonify({"success": False, "message": "Report file not found"}), 404

                report_path = os.path.abspath(history.report_path)
                if not os.path.exists(report_path):
                    return jsonify({"success": False, "message": "Report file not found"}), 404

                return send_from_directory(
                    os.path.dirname(report_path),
                    os.path.basename(report_path),
                    as_attachment=True,
                    download_name=f"github_review_{history_id}.html",
                )
        except Exception as e:
            app.logger.error(f"Failed to download report: {str(e)}")
            return jsonify({"success": False, "message": str(e)})
