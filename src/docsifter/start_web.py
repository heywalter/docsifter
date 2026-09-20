#!/usr/bin/env python3
"""Web UI entry point for DocSifter.

Startup narration goes through the logger rather than a printed banner, so that
``DOCSIFTER_LOG_FORMAT=json`` covers the whole lifetime of the process.
"""

import argparse
import logging
import sys
import webbrowser
from threading import Timer

logger = logging.getLogger(__name__)


def open_browser(port=8080):
    webbrowser.open(f"http://localhost:{port}")


def main():
    from .observability import configure_logging

    configure_logging()
    parser = argparse.ArgumentParser(description="DocSifter Web UI")
    parser.add_argument("--port", type=int, default=8080, help="Server port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open the browser on start"
    )
    args = parser.parse_args()

    try:
        from .orchestrator import DocumentReviewer
        from .web_app import create_flask_app, validate_server_bind

        # Checked before anything is announced, so a refused bind does not first
        # print a URL that will never serve.
        validate_server_bind(args.host)

        logger.info("starting DocSifter Web UI on http://localhost:%s", args.port)
        if args.host in ("0.0.0.0", "::"):
            logger.info("reachable from the network on port %s", args.port)

        reviewer = DocumentReviewer(server_mode=True)
        app = create_flask_app(reviewer)
        if not args.no_browser:
            timer = Timer(3.0, lambda: open_browser(args.port))
            timer.daemon = True
            timer.start()
        # Never debug=True: the Flask debugger would expose an interactive
        # console on any traceback, including to an authenticated operator.
        app.run(host=args.host, port=args.port, debug=False)

    except KeyboardInterrupt:
        logger.info("server stopped")
    except RuntimeError as e:
        # A refused bind or a missing administrator token: the message says what
        # to set, and a traceback would only bury it.
        logger.error("cannot start: %s", e)
        sys.exit(1)
    except ImportError as e:
        # Either a missing dependency or an incomplete install; both are
        # fixed the same way, and guessing which would mislead.
        logger.error("failed to start: %s", e)
        logger.error(
            "the install looks incomplete; reinstall with "
            '"pip install docsifter" or "pip install -e ." from a checkout'
        )
        sys.exit(1)
    except Exception:
        logger.exception("failed to start the Web UI")
        sys.exit(1)


if __name__ == "__main__":
    main()
