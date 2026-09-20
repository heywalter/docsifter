"""The DocSifter Web UI, split by concern.

``app`` holds the factory; ``security`` holds the bind rules and the
administrator gate; each ``routes_*`` module owns one group of endpoints.
Import :func:`docsifter.web_app.create_flask_app` rather than reaching in here.
"""

from .app import create_flask_app
from .security import validate_server_bind

__all__ = ["create_flask_app", "validate_server_bind"]
