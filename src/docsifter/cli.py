"""Command-line entry point for DocSifter document review.

Output is split deliberately. Progress and diagnostics go through the logger,
so ``DOCSIFTER_LOG_FORMAT=json`` produces a parseable stream; the review's
result -- the report path and the statistics block -- is printed to stdout,
because that is what a caller pipes or reads.
"""

import argparse
import logging
import os
import sys

from .corrector import ModelReviewError
from .observability import configure_logging
from .orchestrator import DocumentReviewer
from .web_app import create_flask_app, validate_server_bind

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DocSifter local small-model documentation review tool"
    )
    parser.add_argument("directory", nargs="?", default=".", help="Directory to review")
    parser.add_argument("--config", help="Optional config file path")
    parser.add_argument("--output", default="report.html", help="Output HTML report path")
    parser.add_argument("--server", action="store_true", help="Start web server mode")
    parser.add_argument("--port", type=int, default=8080, help="Web server port")
    parser.add_argument("--host", default="127.0.0.1", help="Web server host")
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Log per-line review detail at DEBUG level. This does not enable the "
            "Flask debugger; the Web server never runs with it."
        ),
    )
    parser.add_argument("--model", help="Enable local model correction and specify model name")
    return parser


def main():
    args = build_parser().parse_args()
    # --debug asks for the review traces, which the engine emits at DEBUG.
    configure_logging(level="DEBUG" if args.debug else None)

    if args.server:
        try:
            validate_server_bind(args.host)
        except RuntimeError as e:
            print(f"Cannot start the server: {e}", file=sys.stderr)
            sys.exit(1)

    reviewer = DocumentReviewer(args.config, server_mode=args.server)
    if not args.model and not args.server:
        print(
            "Mode: rule-preview (no AI model). "
            "For AI correction, add: --model shibing624/chinese-text-correction-1.5b"
        )

    if args.server:
        run_server(reviewer, args)
    else:
        run_review(reviewer, args)


def run_server(reviewer: DocumentReviewer, args) -> None:
    """Serve the Web UI.

    ``debug`` is pinned off: Flask's debugger exposes an interactive console on
    every traceback, and --debug is about review verbosity, not that.
    """
    print(f"Starting web server at http://{args.host}:{args.port}")
    app = create_flask_app(reviewer)
    app.run(host=args.host, port=args.port, debug=False)


def run_review(reviewer: DocumentReviewer, args) -> None:
    """Run one local review and print its result."""
    logger.info("CLI review starting: %s", args.directory)

    if not os.path.exists(args.directory):
        print(f"Error: directory not found - {args.directory}", file=sys.stderr)
        sys.exit(1)

    try:
        result = reviewer.run_local_review(
            args.directory,
            debug=args.debug,
            model=args.model or "rule-based",
            auto_generate=True,
            output_file=args.output,
        )
    except ModelReviewError as e:
        print(f"Model review failed: {e}", file=sys.stderr)
        sys.exit(2)

    if result.get("report_path"):
        html_file = result["report_path"]
        print(f"\nReport generated: {html_file}")
        print(f"Open in browser: file://{os.path.abspath(html_file)}")
    else:
        print("\nNo issues found")

    reviewer.stats = result["stats"]
    print(reviewer.format_stats())


if __name__ == "__main__":
    main()
