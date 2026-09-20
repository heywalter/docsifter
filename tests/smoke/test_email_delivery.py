"""End-to-end email delivery over a real SMTP conversation.

These tests drive smtplib against a loopback server (``smtp_stub``) instead of
replacing the send method, so they cover the connection, the optional login,
the envelope, and the MIME structure that actually reaches a mail server.
"""

import email
import json

import pytest
from smtp_stub import FakeSMTPServer

from docsifter.config import ConfigManager
from docsifter.email_notification import EmailNotificationService


@pytest.fixture
def smtp_server():
    server = FakeSMTPServer()
    yield server
    server.stop()


def _service(tmp_path, port, **overrides):
    settings = {
        "email_smtp_server": "127.0.0.1",
        "email_smtp_port": port,
        "email_use_tls": False,
        "email_sender": "docsifter@example.com",
        "email_recipients": ["walter@example.com"],
        "email_notifications_enabled": True,
    }
    settings.update(overrides)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(settings), encoding="utf-8")
    return EmailNotificationService(ConfigManager(str(config_path)))


def _received(server):
    assert server.messages, "the SMTP server received nothing"
    return email.message_from_string(server.messages[-1]["data"])


def test_a_test_email_reaches_the_server_with_credentials(tmp_path, smtp_server):
    service = _service(
        tmp_path, smtp_server.port, email_username="docsifter", email_password="hunter2"
    )

    result = service.send_test_email()

    assert result["success"] is True
    assert smtp_server.credentials == [("docsifter", "hunter2")]
    message = _received(smtp_server)
    assert message["To"] == "walter@example.com"
    assert message["From"] == "docsifter@example.com"


def test_an_unauthenticated_relay_is_supported(tmp_path, smtp_server):
    """A relay on a closed network usually wants no credentials at all.

    Requiring them would make the tool unusable on exactly the networks it is
    built for, so an empty username means the session skips AUTH entirely.
    """
    service = _service(tmp_path, smtp_server.port, email_username="", email_password="")

    assert service.is_configured() is True
    result = service.send_test_email()

    assert result["success"] is True
    assert smtp_server.credentials == [], "no AUTH should have been attempted"
    assert _received(smtp_server)["Subject"] == "DocSifter - Email configuration test"


def test_a_test_send_does_not_need_notifications_switched_on(tmp_path, smtp_server):
    """The point of a test send is to check the settings before enabling them."""
    service = _service(tmp_path, smtp_server.port, email_notifications_enabled=False)

    assert service.send_test_email("qa@example.com")["success"] is True
    assert _received(smtp_server)["To"] == "qa@example.com"


def test_a_test_send_still_reports_what_is_missing(tmp_path, smtp_server):
    assert (
        _service(tmp_path, smtp_server.port, email_smtp_server="").send_test_email()["message"]
        == "SMTP server not configured"
    )
    assert (
        _service(tmp_path, smtp_server.port, email_sender="").send_test_email()["message"]
        == "Sender address not configured"
    )
    assert (
        _service(tmp_path, smtp_server.port, email_recipients=[]).send_test_email()["message"]
        == "No recipient email configured"
    )


def test_the_report_is_attached_and_every_recipient_is_addressed(tmp_path, smtp_server):
    report = tmp_path / "report.html"
    report.write_text("<html><body>findings</body></html>", encoding="utf-8")
    service = _service(
        tmp_path,
        smtp_server.port,
        email_recipients=["walter@example.com", "team@example.com"],
        attach_report=True,
    )

    result = service.send_report_notification(
        "task-1",
        str(report),
        {"total_files": 2, "valid_changes": 6, "defect_rate_per_thousand": 11.0},
        {"task_id": "task-1", "directory": "./docs", "status": "completed"},
    )

    assert result["success"] is True
    envelope = smtp_server.messages[-1]
    assert len(envelope["rcpt_to"]) == 2
    message = _received(smtp_server)
    attachments = [part.get_filename() for part in message.walk() if part.get_filename()]
    assert attachments == ["report.html"]


def test_a_rejected_login_is_reported_and_not_retried(tmp_path):
    """Repeating a rejected login is how an account gets locked."""
    server = FakeSMTPServer(reject_auth=True)
    try:
        service = _service(
            tmp_path, server.port, email_username="docsifter", email_password="wrong"
        )
        result = service.send_test_email()

        assert result["success"] is False
        assert "535" in result["message"]
        # smtplib may try more than one AUTH mechanism within a session; what
        # matters is that the service did not reconnect and try again.
        assert server.sessions == 1, "a permanent failure must not be retried"
    finally:
        server.stop()
