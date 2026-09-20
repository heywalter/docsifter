"""Flask application factory for the DocSifter Web UI.

The factory does three things in order: validate that this deployment is
allowed to serve where it is about to serve, bring the persistence layer to a
usable state, and then attach the route groups. Each group lives in its own
``routes_*`` module and registers itself against the app, the same way
:func:`docsifter.webhook.register_github_routes` does.
"""

import logging
from pathlib import Path

from flask import Flask

from ..orchestrator import DocumentReviewer
from ..retention import purge_expired_data
from ..webhook import register_github_routes
from .errors import register_error_handlers
from .routes_config import register_config_routes
from .routes_false_positives import register_false_positive_routes
from .routes_history import register_history_routes
from .routes_review import register_review_routes
from .security import register_security, validate_public_url_config

logger = logging.getLogger(__name__)

# Templates and static assets stay at the package root; only the Python moved
# into this subpackage.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def create_flask_app(reviewer: DocumentReviewer) -> Flask:
    """Build the Web application around an existing reviewer."""
    admin_token = validate_public_url_config()

    app = Flask(
        __name__,
        template_folder=str(_PACKAGE_ROOT / "templates"),
        static_folder=str(_PACKAGE_ROOT / "static"),
    )

    _prepare_persistence(reviewer)

    register_security(app, admin_token)
    register_review_routes(app, reviewer)
    register_history_routes(app, reviewer)
    register_config_routes(app, reviewer)
    register_false_positive_routes(app, reviewer)
    register_github_routes(app, reviewer)
    register_error_handlers(app)

    return app


def _prepare_persistence(reviewer: DocumentReviewer) -> None:
    """Recover interrupted work, then age out whatever is past retention."""
    reviewer.history_manager.recover_interrupted_tasks()
    try:
        from .. import models

        models.init_db()
        models.recover_interrupted_reviews()
    except Exception:
        # The local review path does not need the GitHub tables, so a failure
        # here degrades PR monitoring rather than stopping the server.
        logger.exception("GitHub monitor database init failed")

    # Runs after init_db so the GitHub tables exist, and after recovery so an
    # interrupted review is recorded before it can be aged out.
    purge_expired_data(reviewer.history_manager, reviewer.config.get("retention_days"))
