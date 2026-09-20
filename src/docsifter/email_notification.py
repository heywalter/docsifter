"""Email delivery of review reports."""

import logging
import os
import re
import smtplib
import ssl
import time
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any, Dict, List

from .config import ConfigManager

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTACHMENT_MB = 10

PERMANENT_SMTP_ERRORS = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPNotSupportedError,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
)


class EmailConfigError(ValueError):
    """Raised when a submitted email setting cannot be used as given."""


def _coerce_port(value: Any) -> int:
    """Ports must be real integers: `"465"` would silently miss the SSL branch."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as e:
        raise EmailConfigError(f"SMTP port must be a number, got {value!r}") from e
    if not 1 <= port <= 65535:
        raise EmailConfigError(f"SMTP port must be between 1 and 65535, got {port}")
    return port


def _coerce_address(value: Any, field: str) -> str:
    address = str(value or "").strip()
    if not address:
        return ""
    if any(ch in address for ch in "\r\n"):
        raise EmailConfigError(f"{field} must not contain line breaks")
    if address.count("@") != 1 or address.startswith("@") or address.endswith("@"):
        raise EmailConfigError(f"{field} is not a valid email address: {address!r}")
    return address


def _coerce_recipients(value: Any) -> List[str]:
    """Accept a list or a separated string.

    A bare string used to be stored as-is and then joined character by
    character, producing a To header like ``a, @, e, x, ...``.
    """
    if isinstance(value, str):
        candidates = [part for part in re.split(r"[,;\s]+", value) if part]
    elif isinstance(value, (list, tuple)):
        candidates = [str(part).strip() for part in value if str(part).strip()]
    else:
        raise EmailConfigError(f"Recipients must be a list or a separated string, got {value!r}")
    return [_coerce_address(item, "Recipient") for item in candidates]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_text(value: Any) -> str:
    text = str(value or "").strip()
    if any(ch in text for ch in "\r\n"):
        raise EmailConfigError("Value must not contain line breaks")
    return text


def _coerce_positive_int(value: Any) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as e:
        raise EmailConfigError(f"Expected a number, got {value!r}") from e
    if number < 1:
        raise EmailConfigError(f"Expected a positive number, got {number}")
    return number


# The only settings this endpoint accepts. Note that the notification toggles
# carry no `email_` prefix; an earlier prefix filter silently discarded them,
# so turning one off in the Web UI reported success and changed nothing.
EMAIL_FIELD_COERCERS = {
    "email_smtp_server": _coerce_text,
    "email_smtp_port": _coerce_port,
    "email_username": _coerce_text,
    "email_password": _coerce_text,
    "email_use_tls": _coerce_bool,
    "email_sender": lambda v: _coerce_address(v, "Sender"),
    "email_recipients": _coerce_recipients,
    "email_subject_template": _coerce_text,
    "email_notifications_enabled": _coerce_bool,
    "email_max_attachment_mb": _coerce_positive_int,
    "notify_on_local_complete": _coerce_bool,
    "notify_on_github_complete": _coerce_bool,
    "notify_on_error": _coerce_bool,
    "attach_report": _coerce_bool,
}


class EmailNotificationService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.logger = logger
        self.smtp_server = self.config.config.get("email_smtp_server", "")
        self.smtp_port = self.config.config.get("email_smtp_port", 587)
        self.smtp_username = self.config.config.get("email_username", "")
        self.smtp_password = self.config.config.get("email_password", "")
        self.sender_email = self.config.config.get("email_sender", "")
        self.recipient_emails = self.config.config.get("email_recipients", [])
        self.is_enabled = self.config.config.get("email_notifications_enabled", False)
        self.use_tls = self.config.config.get("email_use_tls", True)
        self.max_retries = 3
        self.retry_delay = 2  # seconds

        self.ssl_context = ssl.create_default_context()

    def _create_smtp_connection(self):
        try:
            if self.smtp_port == 465:
                server = smtplib.SMTP_SSL(
                    self.smtp_server, self.smtp_port, timeout=30, context=self.ssl_context
                )
                self.logger.debug("Connected to SMTP server via SSL")
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
                if self.use_tls:
                    server.starttls(context=self.ssl_context)
                    self.logger.debug("Connected to SMTP server via TLS")

            # Only echo the SMTP conversation when debug logging is enabled.
            server.set_debuglevel(1 if self.logger.isEnabledFor(logging.DEBUG) else 0)

            # An internal relay on a closed network commonly accepts mail on
            # port 25 with no authentication at all. Calling login() there fails
            # the connection outright, so credentials stay optional.
            if self.smtp_username:
                self.logger.debug("Logging in as: %s", self.smtp_username)
                server.login(self.smtp_username, self.smtp_password)
                self.logger.debug("SMTP login successful")
            else:
                self.logger.debug("No SMTP username configured, sending unauthenticated")

            return server
        except smtplib.SMTPAuthenticationError as e:
            self.logger.error("SMTP authentication failed: %s", str(e))
            raise
        except ssl.SSLError as e:
            self.logger.error("SSL/TLS error: %s", str(e))
            raise
        except Exception as e:
            self.logger.error("Failed to create SMTP connection: %s", str(e))
            raise

    @staticmethod
    def _is_permanent_failure(error: Exception) -> bool:
        """Is retrying this pointless (and possibly harmful)?

        Repeating a rejected login is the case that matters: providers such as
        Gmail and Microsoft 365 treat repeated failed logins as an attack and
        may lock the account, and no amount of waiting fixes a wrong password.
        """
        if isinstance(error, PERMANENT_SMTP_ERRORS):
            return True
        # RFC 5321: 5xx is a permanent negative reply, 4xx is transient.
        code = getattr(error, "smtp_code", None)
        return isinstance(code, int) and 500 <= code < 600

    def _send_email_with_retry(self, msg, test_mode=False):
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                server = self._create_smtp_connection()
                try:
                    self.logger.debug("Sending email to: %s", msg["To"])
                    result = server.send_message(msg)

                    if not result:
                        if test_mode:
                            self.logger.info("Test email sent successfully")
                        try:
                            server.quit()
                        except Exception:
                            pass
                        return True
                    else:
                        raise Exception(f"Send failed, undelivered recipients: {result}")

                except Exception:
                    try:
                        server.quit()
                    except Exception:
                        pass
                    raise

            except Exception as e:
                last_exception = e
                if self._is_permanent_failure(e):
                    self.logger.error("Permanent send failure, not retrying: %s", str(e))
                    raise
                self.logger.warning("Attempt %s failed: %s", attempt + 1, str(e))

                if attempt < self.max_retries - 1:
                    retry_delay = self.retry_delay * (2**attempt)
                    self.logger.info("Retrying in %ss...", retry_delay)
                    time.sleep(retry_delay)

        if last_exception:
            self.logger.error("All send attempts failed: %s", str(last_exception))
            raise last_exception
        return False

    def is_configured(self) -> bool:
        """Is there enough here to send mail?

        Credentials are deliberately absent: an internal relay that accepts
        unauthenticated mail is a supported setup, and requiring a username
        would make this tool unusable on exactly the closed networks it is
        built for.
        """
        return all(
            [
                self.smtp_server,
                self.smtp_port,
                self.sender_email,
                self.recipient_emails,
            ]
        )

    def update_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            unsupported = sorted(set(config_data) - set(EMAIL_FIELD_COERCERS))
            if unsupported:
                return {
                    "success": False,
                    "message": f"Unsupported email settings: {', '.join(unsupported)}",
                }

            # Validate everything before writing anything, so a rejected field
            # cannot leave half of the settings applied.
            validated = {}
            for key, value in config_data.items():
                if key == "email_password" and (not value or value == "******"):
                    continue
                validated[key] = EMAIL_FIELD_COERCERS[key](value)

            for key, value in validated.items():
                self.config.update_config(key, value)

            self.smtp_server = self.config.config.get("email_smtp_server", "")
            self.smtp_port = self.config.config.get("email_smtp_port", 587)
            self.smtp_username = self.config.config.get("email_username", "")
            self.smtp_password = self.config.config.get("email_password", "")
            self.sender_email = self.config.config.get("email_sender", "")
            self.recipient_emails = self.config.config.get("email_recipients", [])
            self.is_enabled = self.config.config.get("email_notifications_enabled", False)
            self.use_tls = self.config.config.get("email_use_tls", True)

            return {"success": True, "message": "Email config updated"}
        except EmailConfigError as e:
            return {"success": False, "message": str(e)}
        except Exception as e:
            self.logger.error("Failed to update email config: %s", str(e))
            return {"success": False, "message": f"Failed to update email config: {str(e)}"}

    def get_config(self) -> Dict[str, Any]:
        current_password = self.config.config.get("email_password", "")
        return {
            "email_smtp_server": self.smtp_server,
            "email_smtp_port": self.smtp_port,
            "email_username": self.smtp_username,
            "email_password": "******" if current_password else "",
            "email_use_tls": self.use_tls,
            "email_sender": self.sender_email,
            "email_recipients": self.recipient_emails,
            "email_subject_template": self.config.config.get(
                "email_subject_template", "DocSifter Review [TASK_ID] completed"
            ),
            "notify_on_local_complete": self.config.config.get("notify_on_local_complete", True),
            "notify_on_github_complete": self.config.config.get("notify_on_github_complete", True),
            "notify_on_error": self.config.config.get("notify_on_error", True),
            "attach_report": self.config.config.get("attach_report", True),
            "email_notifications_enabled": self.is_enabled,
            "is_configured": self.is_configured(),
        }

    def _attach_report(self, msg, report_path: str) -> bool:
        """Attach the report unless it would push the message over the limit.

        Base64 inflates the payload by about a third, and most providers reject
        messages above roughly 10-25 MB. Silently exceeding that turned a large
        review into no notification at all, so an oversized report is skipped
        and the recipient still gets the summary.
        """
        limit_mb = int(self.config.config.get("email_max_attachment_mb", DEFAULT_MAX_ATTACHMENT_MB))
        raw_size = os.path.getsize(report_path)
        encoded_size = raw_size * 4 // 3

        if encoded_size > limit_mb * 1024 * 1024:
            self.logger.warning(
                f"Report not attached: {encoded_size / 1024 / 1024:.1f} MB encoded "
                f"exceeds the {limit_mb} MB limit. The summary is still being sent."
            )
            return False

        with open(report_path, "rb") as file:
            attachment = MIMEApplication(file.read(), Name=os.path.basename(report_path))
            attachment["Content-Disposition"] = (
                f'attachment; filename="{os.path.basename(report_path)}"'
            )
            msg.attach(attachment)
        return True

    def send_report_notification(
        self, task_id: str, report_path: str, stats: Dict[str, Any], task_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            if not self.is_enabled or not self.is_configured():
                return {
                    "success": False,
                    "message": "Email notification disabled or not configured",
                }

            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = ", ".join(self.recipient_emails)
            msg["Subject"] = self._format_subject(task_id, task_info)

            html_body = self._generate_email_body(task_id, stats, task_info)
            msg.attach(MIMEText(html_body, "html"))

            if self.config.config.get("attach_report", True) and os.path.exists(report_path):
                self._attach_report(msg, report_path)

            self._send_email_with_retry(msg)

            self.logger.info("Report notification sent: task %s", task_id)
            return {"success": True, "message": "Report notification sent"}

        except Exception as e:
            self.logger.error("Failed to send report notification: %s", str(e))
            return {"success": False, "message": f"Failed to send report notification: {str(e)}"}

    def _format_subject(self, task_id: str, task_info: Dict[str, Any]) -> str:
        template = self.config.config.get(
            "email_subject_template", "DocSifter Review [TASK_ID] completed"
        )
        task_type = task_info.get("task_type") or task_info.get("type") or "local"
        replacements = {
            "[TASK_ID]": task_id,
            "{task_id}": task_id,
            "{task_type}": str(task_type),
            "{date}": datetime.now().strftime("%Y-%m-%d"),
        }
        subject = str(template)
        for placeholder, value in replacements.items():
            subject = subject.replace(placeholder, value)
        return " ".join(subject.replace("\r", " ").replace("\n", " ").split())

    def send_error_notification(
        self, task_id: str, error_message: str, task_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        try:
            if not self.config.config.get("notify_on_error", True):
                return {"success": False, "message": "Error notifications disabled"}
            if not self.is_enabled or not self.is_configured():
                return {
                    "success": False,
                    "message": "Email notification disabled or not configured",
                }

            source = task_info.get("directory") or task_info.get("repo_url") or "unknown"
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = ", ".join(self.recipient_emails)
            msg["Subject"] = f"DocSifter review failed - {task_id}"
            body = (
                "<html><body>"
                "<h2>DocSifter review failed</h2>"
                f"<p><strong>Task:</strong> {escape(task_id)}</p>"
                f"<p><strong>Source:</strong> {escape(str(source))}</p>"
                f"<p><strong>Error:</strong> {escape(str(error_message))}</p>"
                "</body></html>"
            )
            msg.attach(MIMEText(body, "html", "utf-8"))
            self._send_email_with_retry(msg)
            return {"success": True, "message": "Error notification sent"}
        except Exception as e:
            self.logger.error("Failed to send error notification: %s", str(e))
            return {"success": False, "message": f"Failed to send error notification: {str(e)}"}

    def _generate_email_body(
        self, task_id: str, stats: Dict[str, Any], task_info: Dict[str, Any]
    ) -> str:
        task_type = task_info.get("task_type", "local")
        task_type_display = {
            "local": "Local directory review",
            "github": "GitHub repository review",
            "github_pr": "GitHub PR review",
            "github_monitor": "GitHub monitor review",
        }.get(task_type, "Document review")

        source = task_info.get("source", "")
        if not source:
            source = task_info.get("directory", task_info.get("repo_url", "local documents"))
        safe_task_id = escape(str(task_id))
        safe_source = escape(str(source))
        public_url = os.getenv("DOCSIFTER_PUBLIC_URL", "").strip().rstrip("/")
        safe_public_url = escape(public_url or "http://localhost:8080", quote=True)

        status = task_info.get("status", "completed")
        status_display = {
            "completed": "Completed",
            "failed": "Failed",
            "cancelled": "Cancelled",
            "running": "Running",
        }.get(status, "Completed")

        def format_time(time_str):
            if not time_str or time_str == "unknown":
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                if isinstance(time_str, str):
                    time_obj = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                else:
                    time_obj = time_str
                return time_obj.strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                return str(time_str)

        created_at = format_time(task_info.get("created_at"))
        end_time = task_info.get("end_time") or task_info.get("completed_at")
        if status in ("completed", "failed", "cancelled") and end_time:
            completed_at = format_time(end_time)
        else:
            completed_at = "In progress"

        html = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        margin: 0;
                        padding: 20px;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                    }}
                    .container {{
                        max-width: 650px;
                        margin: 0 auto;
                        background-color: white;
                        border-radius: 12px;
                        overflow: hidden;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                    }}
                    .header {{
                        background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
                        color: white;
                        padding: 40px 30px;
                        text-align: center;
                    }}
                    .header h1 {{
                        margin: 0 0 10px 0;
                        font-size: 28px;
                        font-weight: 600;
                    }}
                    .content {{
                        padding: 40px 30px;
                    }}
                    .task-info {{
                        background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
                        padding: 25px;
                        border-radius: 8px;
                        margin: 25px 0;
                        border-left: 4px solid #4f46e5;
                    }}
                    .task-info-item {{
                        display: flex;
                        justify-content: space-between;
                        padding: 8px 0;
                        border-bottom: 1px solid #e2e8f0;
                    }}
                    .task-info-item:last-child {{
                        border-bottom: none;
                    }}
                    .stats-grid {{
                        display: grid;
                        grid-template-columns: repeat(2, 1fr);
                        gap: 15px;
                        margin: 25px 0;
                    }}
                    .stat-card {{
                        background: #f8fafc;
                        padding: 20px;
                        border-radius: 8px;
                        text-align: center;
                        border: 1px solid #e2e8f0;
                    }}
                    .stat-number {{
                        font-size: 24px;
                        font-weight: 700;
                        color: #4f46e5;
                        margin-bottom: 5px;
                    }}
                    .stat-label {{
                        font-size: 14px;
                        color: #6b7280;
                    }}
                    .footer {{
                        background-color: #f8fafc;
                        padding: 25px 30px;
                        text-align: center;
                        color: #6b7280;
                        font-size: 14px;
                    }}
                    .success-badge {{
                        background: #10b981;
                        color: white;
                        padding: 4px 12px;
                        border-radius: 20px;
                        font-size: 14px;
                        font-weight: 600;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>DocSifter Review Complete</h1>
                        <p>Report for task {safe_task_id}</p>
                    </div>

                    <div class="content">
                        <h2 style="color: #374151; margin-bottom: 20px;">Task Details</h2>
                        <div class="task-info">
                            <div class="task-info-item">
                                <span style="font-weight: 600; color: #374151;">Task type</span>
                                <span style="color: #6b7280;">{task_type_display}</span>
                            </div>
                            <div class="task-info-item">
                                <span style="font-weight: 600; color: #374151;">Source</span>
                                <span style="color: #6b7280;">{safe_source}</span>
                            </div>
                            <div class="task-info-item">
                                <span style="font-weight: 600; color: #374151;">Status</span>
                                <span class="success-badge">{status_display}</span>
                            </div>
                            <div class="task-info-item">
                                <span style="font-weight: 600; color: #374151;">Started</span>
                                <span style="color: #6b7280;">{created_at}</span>
                            </div>
                            <div class="task-info-item">
                                <span style="font-weight: 600; color: #374151;">Completed</span>
                                <span style="color: #6b7280;">{completed_at}</span>
                            </div>
                        </div>

                        <h2 style="color: #374151; margin-bottom: 20px;">Statistics</h2>
                        <div class="stats-grid">
                            <div class="stat-card">
                                <div class="stat-number">{stats.get("total_files", 0)}</div>
                                <div class="stat-label">Files scanned</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">{stats.get("valid_changes", 0)}</div>
                                <div class="stat-label">Valid corrections</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">{stats.get("total_changes", 0)}</div>
                                <div class="stat-label">Total changes</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number">{stats.get("defect_rate_per_thousand", 0):.1f}‰</div>
                                <div class="stat-label">Defect rate (per 1k chars)</div>
                            </div>
                        </div>

                        <div style="background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px; padding: 20px; margin: 25px 0;">
                            <p style="margin: 0; color: #92400e; font-weight: 600;">
                                The detailed review report is attached. Open the attachment to see all corrections.
                            </p>
                        </div>

                        <div style="text-align: center;">
                            <a href="{safe_public_url}" style="display: inline-block; padding: 12px 24px; background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); color: white; text-decoration: none; border-radius: 6px; font-weight: 600;">Open DocSifter</a>
                        </div>
                    </div>

                    <div class="footer">
                        <p><strong>DocSifter</strong></p>
                        <p>Sent at: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} — automated notification, do not reply</p>
                    </div>
                </div>
            </body>
        </html>
        """

        return html

    def send_test_email(self, test_recipient: str | None = None) -> Dict[str, Any]:
        try:
            # Deliberately not gated on email_notifications_enabled: the point
            # of a test send is to find out whether the settings work before
            # turning automatic notifications on.
            if not self.smtp_server:
                return {"success": False, "message": "SMTP server not configured"}
            if not self.sender_email:
                return {"success": False, "message": "Sender address not configured"}

            recipients = (
                [test_recipient.strip()] if test_recipient and test_recipient.strip() else []
            )
            if not recipients:
                recipients = self.recipient_emails

            if not recipients:
                return {"success": False, "message": "No recipient email configured"}

            msg = self._create_test_email(recipients)
            self._send_email_with_retry(msg, test_mode=True)

            return {"success": True, "message": "Test email sent successfully"}

        except Exception as e:
            error_msg = f"Failed to send test email: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg}

    def _create_test_email(self, recipients: List[str] | None = None) -> MIMEMultipart:
        recipients = recipients or self.recipient_emails
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = "DocSifter - Email configuration test"

        test_html = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #4a6ee0; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
                    .content {{ background-color: #f9f9f9; padding: 20px; border-radius: 0 0 5px 5px; }}
                    .success {{ background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1 style="margin:0;">Email configuration test</h1>
                        <p style="margin:5px 0 0 0;">DocSifter</p>
                    </div>
                    <div class="content">
                        <div class="success">
                            <h2 style="margin-top:0;">Email configuration test successful!</h2>
                            <p>Your email configuration is correct. The system can send notification emails.</p>
                        </div>

                        <h3>Configuration:</h3>
                        <ul>
                            <li><strong>SMTP server:</strong> {self.smtp_server}</li>
                            <li><strong>SMTP port:</strong> {self.smtp_port}</li>
                            <li><strong>Sender:</strong> {self.sender_email}</li>
                            <li><strong>Recipients:</strong> {", ".join(recipients)}</li>
                            <li><strong>Sent at:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</li>
                        </ul>

                        <p style="margin-top: 30px; color: #666;">
                            This is an automated test email to verify your email configuration.
                            If you received this, email notifications are working correctly.
                        </p>
                    </div>
                </div>
            </body>
        </html>
        """

        msg.attach(MIMEText(test_html, "html"))
        return msg


def get_email_service(config: ConfigManager) -> EmailNotificationService:
    return EmailNotificationService(config)
