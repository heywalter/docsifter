"""Routes for the terminology allowlist and the false-positive store.

Both lists are read by the correction engine on every review, so every mutation
here takes ``reviewer.review_lock`` before touching them.
"""

import logging

from flask import jsonify, request

from ..runtime import utcnow
from .errors import api_error, server_error

logger = logging.getLogger(__name__)

# A single request may not rewrite the whole store in one go; the cap keeps a
# runaway client from turning one POST into an unbounded write.
MAX_BATCH_ITEMS = 5000


def register_false_positive_routes(app, reviewer) -> None:
    """Attach the allowlist and false-positive routes to ``app``."""

    @app.route("/api/whitelist", methods=["GET", "POST"])
    def manage_whitelist():
        if request.method == "GET":
            return jsonify({"success": True, "data": reviewer.config.get("whitelist", [])})

        try:
            data = request.json
            if isinstance(data, list):
                whitelist_items = data
            elif isinstance(data, dict) and "whitelist" in data:
                whitelist_items = data["whitelist"]
            else:
                return jsonify({"success": False, "message": "Invalid whitelist format"})

            if not isinstance(whitelist_items, list):
                return jsonify({"success": False, "message": "Whitelist must be an array"})

            reviewer.update_config("whitelist", whitelist_items)
            return jsonify({"success": True, "message": "Whitelist updated"})
        except Exception as e:
            return server_error("update whitelist", e)

    @app.route("/api/false_positives", methods=["GET", "POST", "DELETE"])
    def manage_false_positives():
        try:
            if request.method == "GET":
                with reviewer.review_lock:
                    items = list(reviewer.false_positive_manager.false_positives)
                return jsonify({"success": True, "data": items})

            item = normalize_false_positive(request.get_json(silent=True) or {})
            if request.method == "POST":
                with reviewer.review_lock:
                    reviewer.false_positive_manager.add_false_positive(**item)
                return jsonify({"success": True, "message": "False positive added"})

            removed_count = _remove_matching(reviewer, {false_positive_identity(item)})
            if not removed_count:
                return api_error("False positive not found", 404)
            return jsonify({"success": True, "removed_count": removed_count})
        except ValueError as e:
            # Raised by normalize_false_positive with text written for the caller.
            return api_error(str(e), 400)
        except Exception as e:
            return server_error("manage false positives", e)

    @app.route("/api/false_positives/batch", methods=["DELETE"])
    def batch_delete_false_positives():
        try:
            data = request.get_json(silent=True) or {}
            items = data.get("items")
            if not isinstance(items, list) or not items:
                raise ValueError("items must be a non-empty array")
            if len(items) > MAX_BATCH_ITEMS:
                raise ValueError(f"A batch may contain at most {MAX_BATCH_ITEMS} items")

            targets = {false_positive_identity(normalize_false_positive(item)) for item in items}
            return jsonify({"success": True, "removed_count": _remove_matching(reviewer, targets)})
        except ValueError as e:
            return api_error(str(e), 400)
        except Exception as e:
            return server_error("batch delete false positives", e)

    @app.route("/api/false_positives/import", methods=["POST"])
    def import_false_positives():
        try:
            data = request.get_json(silent=True) or {}
            items = data.get("false_positives")
            if not isinstance(items, list):
                raise ValueError("false_positives must be an array")
            if len(items) > MAX_BATCH_ITEMS:
                raise ValueError(f"An import may contain at most {MAX_BATCH_ITEMS} items")

            normalized_items = [
                normalize_false_positive(item, keep_timestamp=True) for item in items
            ]
            with reviewer.review_lock:
                existing = {
                    false_positive_identity(item)
                    for item in reviewer.false_positive_manager.false_positives
                }
                imported = []
                for item in normalized_items:
                    identity = false_positive_identity(item)
                    if identity not in existing:
                        imported.append(item)
                        existing.add(identity)

                if imported:
                    reviewer.false_positive_manager.false_positives.extend(imported)
                    reviewer.false_positive_manager.save_false_positives()

            return jsonify({"success": True, "imported_count": len(imported)})
        except ValueError as e:
            return api_error(str(e), 400)
        except Exception as e:
            return server_error("import false positives", e)


def false_positive_identity(item: dict):
    """The tuple that decides whether two records are the same entry.

    The note is deliberately excluded: re-importing a record with a reworded
    note should not create a duplicate.
    """
    return (
        item.get("original", ""),
        item.get("corrected", ""),
        bool(item.get("is_pattern", False)),
    )


def normalize_false_positive(item: dict, keep_timestamp: bool = False) -> dict:
    """Validate one record and return it in storage shape.

    Raises:
        ValueError: with a message written for the caller, which the routes
            return verbatim as a 400.
    """
    if not isinstance(item, dict):
        raise ValueError("Invalid false-positive item")

    original = item.get("original")
    corrected = item.get("corrected", "")
    note = item.get("note", "")
    is_pattern = item.get("is_pattern", False)
    if not isinstance(original, str) or not original:
        raise ValueError("Each item needs original text")
    if not isinstance(corrected, str) or not isinstance(note, str):
        raise ValueError("Invalid false-positive text")
    if not isinstance(is_pattern, bool):
        raise ValueError("is_pattern must be a boolean")

    normalized = {
        "original": original,
        "corrected": corrected,
        "is_pattern": is_pattern,
        "note": note,
    }
    if keep_timestamp:
        normalized["timestamp"] = str(item.get("timestamp") or utcnow())
    return normalized


def _remove_matching(reviewer, targets: set) -> int:
    """Drop every record whose identity is in ``targets``; return how many went."""
    with reviewer.review_lock:
        false_positives = reviewer.false_positive_manager.false_positives
        original_count = len(false_positives)
        reviewer.false_positive_manager.false_positives = [
            item for item in false_positives if false_positive_identity(item) not in targets
        ]
        removed_count = original_count - len(reviewer.false_positive_manager.false_positives)
        if removed_count:
            reviewer.false_positive_manager.save_false_positives()
    return removed_count
