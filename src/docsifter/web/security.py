"""Bind validation, response headers, and administrator authentication.

DocSifter's Web UI manages review configuration and reads the local filesystem,
so exposing it beyond loopback is a deliberate act that requires an
administrator token. The checks live here rather than in the route modules so
that every route inherits them and none can opt out by accident.
"""

import hmac
import ipaddress
import logging
import os

from flask import jsonify, request

logger = logging.getLogger(__name__)

MIN_ADMIN_TOKEN_LENGTH = 24

# The webhook endpoint authenticates with GitHub's own HMAC signature, so it is
# the one path that must stay reachable without the administrator token.
UNAUTHENTICATED_PATHS = frozenset({"/api/github/webhook"})


def _is_loopback(host: str) -> bool:
    normalized_host = (host or "").strip().strip("[]")
    if normalized_host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False


def validate_server_bind(host: str) -> None:
    """Refuse a non-loopback bind unless a strong administrator token is set."""
    if _is_loopback(host):
        return

    admin_token = os.getenv("DOCSIFTER_ADMIN_TOKEN", "").strip()
    if not admin_token:
        raise RuntimeError(
            "DOCSIFTER_ADMIN_TOKEN is required when the Web server binds to a non-loopback host"
        )
    if len(admin_token) < MIN_ADMIN_TOKEN_LENGTH:
        raise RuntimeError(
            "DOCSIFTER_ADMIN_TOKEN must contain at least "
            f"{MIN_ADMIN_TOKEN_LENGTH} characters for network access"
        )


def validate_public_url_config() -> str:
    """Validate the deployment's token and return it.

    Announcing a public URL is the other way the UI becomes reachable from
    outside the host, so it carries the same token requirement as a
    non-loopback bind.
    """
    admin_token = os.getenv("DOCSIFTER_ADMIN_TOKEN", "").strip()
    public_url = os.getenv("DOCSIFTER_PUBLIC_URL", "").strip()
    if public_url and not admin_token:
        raise RuntimeError(
            "DOCSIFTER_ADMIN_TOKEN is required when DOCSIFTER_PUBLIC_URL is configured"
        )
    if public_url and len(admin_token) < MIN_ADMIN_TOKEN_LENGTH:
        raise RuntimeError(
            "DOCSIFTER_ADMIN_TOKEN must contain at least "
            f"{MIN_ADMIN_TOKEN_LENGTH} characters for public deployments"
        )
    return admin_token


def register_security(app, admin_token: str) -> None:
    """Attach the response headers and the administrator gate to ``app``."""

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        return response

    @app.before_request
    def protect_management_routes():
        if request.path in UNAUTHENTICATED_PATHS or not admin_token:
            return None

        supplied_token = ""
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            supplied_token = authorization[7:].strip()
        elif request.authorization:
            supplied_token = request.authorization.password or ""

        if not supplied_token or not hmac.compare_digest(supplied_token, admin_token):
            response = jsonify({"success": False, "message": "Authentication required"})
            response.status_code = 401
            response.headers["WWW-Authenticate"] = 'Basic realm="DocSifter"'
            return response

        # A browser form can be submitted cross-site with only "simple" headers,
        # so requiring a custom one on every mutation blocks that path.
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("X-DocSifter-Request") != "1"
        ):
            return (
                jsonify({"success": False, "message": "Missing request verification header"}),
                403,
            )

        return None
