"""Routes that read and update runtime configuration.

Three groups live here: the generic config endpoint, the LLM review panel, and
the email panel, plus the directory browser the review form uses to pick a
target. They share one rule -- a setting pinned by an environment variable is an
operator decision, and the Web UI must not quietly outrank it.
"""

import logging
import os

from flask import jsonify, request

from ..email_notification import get_email_service
from ..runtime import resolve_allowed_path
from .constants import (
    CONTEXT_SCOPES,
    EDITABLE_CONFIG_KEYS,
    LLM_BOOL_KEYS,
    LLM_INT_BOUNDS,
    LLM_INT_KEYS,
    LLM_TEXT_KEYS,
    SENSITIVE_CONFIG_KEYS,
    WEB_SUPPORTED_EXTENSIONS,
)
from .errors import api_error, server_error

logger = logging.getLogger(__name__)


def register_config_routes(app, reviewer) -> None:
    """Attach the configuration, LLM, email, and directory routes to ``app``."""

    @app.route("/config", methods=["GET", "POST"])
    def config_api():
        if request.method == "GET":
            public_config = {
                key: value
                for key, value in reviewer.config.items()
                if key not in SENSITIVE_CONFIG_KEYS
            }
            return jsonify(public_config)

        try:
            data = request.get_json(silent=True) or {}
            unsupported_keys = sorted(set(data) - EDITABLE_CONFIG_KEYS)
            if unsupported_keys:
                return api_error(f"Unsupported config keys: {', '.join(unsupported_keys)}", 400)

            for key, value in data.items():
                reviewer.update_config(key, value)
            return jsonify({"success": True, "message": "Config updated"})
        except Exception as e:
            return server_error("update config", e)

    @app.route("/api/llm/config", methods=["GET"])
    def get_llm_config():
        """Report the LLM layer settings, without ever returning the API key."""
        config = reviewer.config
        manager = reviewer.config_manager
        locked = [
            key
            for key in LLM_BOOL_KEYS
            + LLM_TEXT_KEYS
            + LLM_INT_KEYS
            + ("llm_api_key", "context_review_scope")
            if manager.is_environment_locked(key)
        ]
        return jsonify(
            {
                "llm_review_enabled": bool(config.get("llm_review_enabled")),
                "context_review_enabled": bool(config.get("context_review_enabled")),
                "llm_endpoint": config.get("llm_endpoint") or "",
                "llm_model": config.get("llm_model") or "",
                "llm_max_reviews": int(config.get("llm_max_reviews") or 20),
                "llm_timeout_seconds": int(config.get("llm_timeout_seconds") or 60),
                "context_max_files": int(config.get("context_max_files") or 50),
                "pr_llm_enabled": bool(config.get("pr_llm_enabled")),
                "context_review_scope": str(config.get("context_review_scope") or "flagged"),
                # Presence only. The value itself never leaves the process.
                "api_key_configured": bool(config.get("llm_api_key")),
                "environment_locked": locked,
            }
        )

    @app.route("/api/llm/config", methods=["POST"])
    def save_llm_config():
        """Update the LLM layer settings from the Web panel."""
        data = request.get_json(silent=True) or {}
        manager = reviewer.config_manager

        rejection = _reject_unsupported_or_locked(data, manager)
        if rejection:
            return rejection

        updates, rejection = _collect_llm_updates(data, reviewer)
        if rejection:
            return rejection

        try:
            for key, value in updates.items():
                reviewer.update_config(key, value)

            if "llm_api_key" in data:
                # Kept in memory for this process only; never written to disk.
                manager.update_secret("llm_api_key", str(data["llm_api_key"] or ""))
                reviewer.config = manager.get_config()
        except Exception as e:
            return server_error("save LLM settings", e)

        return jsonify({"success": True, "message": "LLM settings updated"})

    @app.route("/api/directories")
    def list_directories():
        try:
            requested_path = request.args.get("path", "./")
            original_cwd = os.getcwd()
            try:
                current_dir = str(resolve_allowed_path(requested_path, original_cwd))
            except PermissionError as e:
                # Names only the path the caller asked for, so it can be echoed.
                return api_error(str(e), 403)

            if not os.path.exists(current_dir) or not os.path.isdir(current_dir):
                return api_error("Directory not found", 404)

            current_path_display = _display_path(current_dir, original_cwd)
            items = [
                {
                    "name": "Current directory",
                    "path": current_path_display,
                    "full_path": current_dir,
                    "type": "current",
                }
            ]
            items.extend(_parent_entry(current_dir, original_cwd))
            items.extend(_child_entries(current_dir, original_cwd))

            return jsonify(
                {"success": True, "directories": items, "current_path": current_path_display}
            )
        except Exception as e:
            return server_error("list directories", e)

    @app.route("/api/email/config", methods=["GET", "POST"])
    def email_config():
        email_service = get_email_service(reviewer.config_manager)

        if request.method == "GET":
            try:
                return jsonify({"success": True, "data": email_service.get_config()})
            except Exception as e:
                return server_error("read email config", e)

        try:
            return jsonify(email_service.update_config(request.get_json()))
        except Exception as e:
            return server_error("update email config", e)

    @app.route("/api/email/test", methods=["POST"])
    def test_email():
        try:
            data = request.get_json(silent=True) or {}
            email_service = get_email_service(reviewer.config_manager)
            return jsonify(email_service.send_test_email(data.get("test_recipient")))
        except Exception as e:
            return server_error("send test email", e)


def _reject_unsupported_or_locked(data: dict, manager):
    """Return an error response when the payload is out of bounds, else None."""
    allowed = set(LLM_BOOL_KEYS + LLM_TEXT_KEYS + LLM_INT_KEYS) | {
        "llm_api_key",
        "context_review_scope",
    }
    unsupported = sorted(set(data) - allowed)
    if unsupported:
        return api_error(f"Unsupported keys: {', '.join(unsupported)}", 400)

    # An environment variable is an operator decision; the Web UI must not
    # quietly outrank it, or a deployment's pinned endpoint could be moved.
    blocked = sorted(key for key in data if manager.is_environment_locked(key))
    if blocked:
        return api_error(
            "These settings are pinned by environment variables and "
            f"cannot be changed here: {', '.join(blocked)}",
            409,
        )
    return None


def _collect_llm_updates(data: dict, reviewer):
    """Validate the payload and return ``(updates, error_response)``."""
    updates = {}
    for key in LLM_BOOL_KEYS:
        if key in data:
            updates[key] = bool(data[key])

    for key in LLM_TEXT_KEYS:
        if key in data:
            updates[key] = str(data[key] or "").strip()

    endpoint = updates.get("llm_endpoint")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        return updates, api_error("Endpoint must start with http:// or https://", 400)

    if "context_review_scope" in data:
        scope = str(data["context_review_scope"] or "").strip().lower()
        if scope not in CONTEXT_SCOPES:
            return updates, api_error(
                f"context_review_scope must be one of {', '.join(CONTEXT_SCOPES)}", 400
            )
        updates["context_review_scope"] = scope

    for key in LLM_INT_KEYS:
        if key not in data:
            continue
        low, high = LLM_INT_BOUNDS[key]
        try:
            number = int(data[key])
        except (TypeError, ValueError):
            return updates, api_error(f"{key} must be a number", 400)
        if not low <= number <= high:
            return updates, api_error(f"{key} must be between {low} and {high}", 400)
        updates[key] = number

    # Enabling a review layer without an endpoint would fail silently at run
    # time (load_llm_reviewer returns None), so refuse it here instead.
    effective_endpoint = updates.get("llm_endpoint", reviewer.config.get("llm_endpoint") or "")
    effective_model = updates.get("llm_model", reviewer.config.get("llm_model") or "")
    for key in ("llm_review_enabled", "context_review_enabled"):
        if updates.get(key) and not (effective_endpoint and effective_model):
            return updates, api_error(
                "Set the endpoint and model before enabling a review layer", 400
            )

    return updates, None


def _display_path(path: str, root: str) -> str:
    """Render ``path`` the way the picker shows it: relative to the start root."""
    relative = os.path.relpath(path, root)
    return "./" if relative == "." else f"./{relative}/"


def _parent_entry(current_dir: str, original_cwd: str) -> list:
    """The ".." entry, omitted at the top of the allowed roots."""
    if current_dir == original_cwd:
        return []

    parent_dir = os.path.dirname(current_dir)
    try:
        resolve_allowed_path(parent_dir)
    except PermissionError:
        return []

    return [
        {
            "name": "Parent directory (..)",
            "path": _display_path(parent_dir, original_cwd),
            "full_path": parent_dir,
            "type": "parent",
        }
    ]


def _child_entries(current_dir: str, original_cwd: str) -> list:
    """Visible subdirectories and reviewable files, in name order."""
    entries = []
    for item in sorted(os.listdir(current_dir)):
        item_path = os.path.join(current_dir, item)
        item_relative = os.path.relpath(item_path, original_cwd)
        item_path_display = "./" if item_relative == "." else f"./{item_relative}"

        if os.path.isdir(item_path) and not item.startswith("."):
            entries.append(
                {
                    "name": item,
                    "path": f"{item_path_display}/",
                    "full_path": item_path,
                    "type": "directory",
                }
            )
        elif item.endswith(WEB_SUPPORTED_EXTENSIONS) and os.path.isfile(item_path):
            entries.append(
                {
                    "name": item,
                    "path": item_path_display,
                    "full_path": item_path,
                    "type": "file",
                }
            )
    return entries
