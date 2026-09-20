"""Production WSGI entry point used by the container image."""

from .orchestrator import DocumentReviewer
from .web_app import create_flask_app

app = create_flask_app(DocumentReviewer(server_mode=True))
