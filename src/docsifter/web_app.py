"""Public entry point for the Web application.

The implementation lives in the :mod:`docsifter.web` package, one module per
route group. This module stays as the single import path used by the CLI, the
WSGI entry point, and the tests.
"""

from .web import create_flask_app, validate_server_bind

__all__ = ["create_flask_app", "validate_server_bind"]
