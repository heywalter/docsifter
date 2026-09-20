"""Uniform API error responses.

Two kinds of failure reach a handler, and they are answered differently:

*Expected* failures -- a malformed payload, a path outside the allowed roots,
an unknown task -- carry a message the caller can act on, and the route returns
it directly.

*Unexpected* failures are bugs or environment problems. Their exception text
tends to carry filesystem paths, SMTP hostnames and database locations, so
:func:`server_error` records the detail in the log, where an operator can read
it, and answers the client with a fixed string. SECURITY.md allows the Web UI
to be reached over a network behind an admin token, so an authenticated caller
should still not be handed the server's internals.
"""

import logging

from flask import jsonify, request

logger = logging.getLogger(__name__)

GENERIC_ERROR_MESSAGE = "Internal server error"


def api_error(message: str, status: int):
    """Answer with a message the caller is meant to read."""
    return jsonify({"success": False, "message": message}), status


def server_error(context: str, exc: BaseException, status: int = 500):
    """Log an unexpected exception and answer with a generic message.

    ``context`` names the operation that failed ("cancel task", "save LLM
    settings") so the log line is searchable without a traceback prefix.
    """
    logger.exception("%s failed", context, exc_info=exc)
    return api_error(GENERIC_ERROR_MESSAGE, status)


def register_error_handlers(app) -> None:
    """Install the JSON error handlers for ``/api/`` routes.

    Non-API paths keep Flask's own HTML error pages, so the browser UI still
    shows a normal 404 instead of a JSON body.
    """

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return api_error("Endpoint not found", 404)
        return error

    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith("/api/"):
            return api_error(GENERIC_ERROR_MESSAGE, 500)
        return error

    @app.errorhandler(Exception)
    def handle_exception(e):
        if request.path.startswith("/api/"):
            return server_error(f"unhandled request to {request.path}", e)
        raise e
