import json
import subprocess
from pathlib import Path

import pytest

from docsifter.config import ConfigManager
from docsifter.email_notification import EmailNotificationService
from docsifter.file_processor import FileProcessor
from docsifter.github_integration import GitHubIntegration, GitHubTaskManager
from docsifter.html_generator import HTMLGenerator


def test_send_test_email_uses_requested_recipient(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "email_notifications_enabled": True,
                "email_smtp_server": "smtp.example.com",
                "email_smtp_port": 587,
                "email_username": "sender@example.com",
                "email_password": "secret",
                "email_sender": "sender@example.com",
                "email_recipients": ["default@example.com"],
            }
        ),
        encoding="utf-8",
    )
    service = EmailNotificationService(ConfigManager(str(config_path)))
    sent = {}

    def fake_send(msg, test_mode=False):
        sent["to"] = msg["To"]
        sent["test_mode"] = test_mode
        return True

    service._send_email_with_retry = fake_send

    result = service.send_test_email("qa@example.com")

    assert result["success"] is True
    assert sent == {"to": "qa@example.com", "test_mode": True}


def test_report_email_honors_subject_template_and_attachment_setting(tmp_path):
    report = tmp_path / "report.html"
    report.write_text("<p>report</p>", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "email_notifications_enabled": True,
                "email_smtp_server": "smtp.example.com",
                "email_smtp_port": 587,
                "email_username": "sender@example.com",
                "email_password": "secret",
                "email_sender": "sender@example.com",
                "email_recipients": ["docs@example.com"],
                "email_subject_template": "[DocSifter] {task_type} [TASK_ID] {date}",
                "attach_report": False,
            }
        ),
        encoding="utf-8",
    )
    service = EmailNotificationService(ConfigManager(str(config_path)))
    sent = {}

    def fake_send(msg, test_mode=False):
        sent["message"] = msg
        return True

    service._send_email_with_retry = fake_send

    result = service.send_report_notification(
        "task-123",
        str(report),
        {"total_files": 1},
        {"task_type": "github_pr", "status": "completed"},
    )

    assert result["success"] is True
    assert "github_pr" in sent["message"]["Subject"]
    assert "task-123" in sent["message"]["Subject"]
    assert all(part.get_content_maintype() != "application" for part in sent["message"].walk())


def test_error_notification_respects_notify_on_error(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "email_notifications_enabled": True,
                "email_smtp_server": "smtp.example.com",
                "email_smtp_port": 587,
                "email_username": "sender@example.com",
                "email_password": "secret",
                "email_sender": "sender@example.com",
                "email_recipients": ["docs@example.com"],
                "notify_on_error": True,
            }
        ),
        encoding="utf-8",
    )
    service = EmailNotificationService(ConfigManager(str(config_path)))
    sent = {}
    service._send_email_with_retry = lambda msg, test_mode=False: sent.setdefault("message", msg)

    result = service.send_error_notification(
        "task-456",
        "model failed",
        {"task_type": "local", "directory": "docs"},
    )

    assert result["success"] is True
    assert "failed" in sent["message"]["Subject"].lower()
    assert "model failed" in sent["message"].get_payload()[0].get_payload(decode=True).decode()


class FakeGitHub:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.cloned_ref = None
        self.cleanup_calls = 0

    def parse_github_url(self, repo_url):
        return {"owner": "acme", "repo": "docs", "branch": "main", "path": ""}

    def clone_repository(self, repo_url, ref=None):
        self.cloned_ref = ref
        return str(self.repo_path)

    def get_pr_changed_files(self, owner, repo, pr_number):
        return [{"filename": "docs/quick-start.md", "status": "modified"}]

    def cleanup(self):
        self.cleanup_calls += 1


class FakeTextCorrector:
    def extract_text_from_file(self, file_path, content):
        return [(1, content, content)]

    def process_file(self, file_path, content):
        return [
            {
                "file_path": file_path,
                "line_number": 1,
                "original_line": content,
                "original_text": "轮循",
                "corrected_text": "轮询",
                "source": "text",
            }
        ]


class FakeFalsePositiveManager:
    def is_false_positive(self, original, corrected):
        return False


class FakeReviewer:
    file_processor = FileProcessor()
    text_corrector = FakeTextCorrector()
    false_positive_manager = FakeFalsePositiveManager()
    html_generator = HTMLGenerator()

    def get_model_info(self):
        return "test model"

    def _is_whitespace_change(self, original, corrected):
        return "".join(original.split()) == "".join(corrected.split())


def test_github_task_generates_report_and_stats(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    docs_dir = repo / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "quick-start.md").write_text("轮循", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    github = FakeGitHub(repo)
    task_manager = GitHubTaskManager(github)
    task_id = task_manager.create_github_task(
        "https://github.com/acme/docs",
        directories=[],
        check_all=False,
        pr_number=12,
        ref="abc123",
    )

    result = task_manager.execute_github_task(task_id, FakeReviewer())

    assert result["success"] is True
    assert result["stats"]["valid_changes"] == 1
    assert result["files_with_issues"] == 1
    assert Path(result["report_path"]).exists()
    assert task_manager.get_task_status(task_id)["status"] == "completed"
    assert github.cloned_ref == "abc123"
    assert github.cleanup_calls == 1


def test_github_task_cancelled_before_execution_does_not_clone(tmp_path):
    github = FakeGitHub(tmp_path)
    task_manager = GitHubTaskManager(github)
    task_id = task_manager.create_github_task(
        "https://github.com/acme/docs",
        directories=[],
        check_all=False,
        pr_number=12,
        ref="refs/pull/12/head",
    )

    assert task_manager.cancel_task(task_id) is True
    result = task_manager.execute_github_task(task_id, FakeReviewer())

    assert result["cancelled"] is True
    assert task_manager.get_task_status(task_id)["status"] == "cancelled"
    assert github.cloned_ref is None
    assert github.cleanup_calls == 1


def test_get_pr_changed_files_paginates(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    github = GitHubIntegration()
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, headers, params, timeout):
        calls.append(params.copy())
        page = params["page"]
        if page == 1:
            payload = [
                {"filename": f"docs/page-{index}.md", "status": "modified"} for index in range(100)
            ]
        else:
            payload = [{"filename": "docs/final.adoc", "status": "added"}]
        return FakeResponse(payload)

    monkeypatch.setattr("docsifter.github_integration.requests.get", fake_get)

    files = github.get_pr_changed_files("acme", "docs", 12)

    assert len(files) == 101
    assert calls == [{"per_page": 100, "page": 1}, {"per_page": 100, "page": 2}]


def test_clone_repository_fetches_requested_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    github = GitHubIntegration()
    github.temp_dir = str(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("docsifter.github_integration.subprocess.run", fake_run)

    checkout = github.clone_repository(
        "https://github.com/acme/docs",
        ref="refs/pull/12/head",
    )

    assert Path(checkout).exists()
    assert ["git", "fetch", "--depth", "1", "origin", "refs/pull/12/head"] in calls
    assert ["git", "checkout", "--detach", "FETCH_HEAD"] in calls


def test_clone_repository_uses_remote_default_without_explicit_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    github = GitHubIntegration()
    github.temp_dir = str(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("docsifter.github_integration.subprocess.run", fake_run)

    checkout = github.clone_repository("https://github.com/acme/docs")

    assert [
        "git",
        "clone",
        "--depth",
        "1",
        "https://github.com/acme/docs.git",
        checkout,
    ] in calls


def test_clone_repository_uses_token_without_exposing_it_in_command(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.sslVerify")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    github = GitHubIntegration({"github_token": "private-token"})
    github.temp_dir = str(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("docsifter.github_integration.subprocess.run", fake_run)

    github.clone_repository("https://github.com/acme/private-docs")

    command, kwargs = calls[0]
    assert "private-token" not in " ".join(command)
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kwargs["env"]["GIT_CONFIG_COUNT"] == "2"
    assert kwargs["env"]["GIT_CONFIG_KEY_0"] == "http.sslVerify"
    assert kwargs["env"]["GIT_CONFIG_VALUE_0"] == "true"
    assert kwargs["env"]["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraHeader"
    assert kwargs["env"]["GIT_CONFIG_VALUE_1"].startswith("Authorization: Basic ")


class _StubConfigManager:
    """Minimal ConfigManager surface used by the LLM loaders."""

    def __init__(self, config):
        self.config = config


class _ModelSourcedCorrector(FakeTextCorrector):
    """Findings the LLM layer is actually eligible to verify."""

    def process_file(self, file_path, content):
        changes = super().process_file(file_path, content)
        for change in changes:
            change["review_source"] = "model"
        return changes


def _pr_reviewer_with_config(config):
    reviewer = FakeReviewer()
    reviewer.text_corrector = _ModelSourcedCorrector()
    reviewer.config = config
    reviewer.config_manager = _StubConfigManager(config)
    return reviewer


def _llm_layers_config(**overrides):
    config = {
        "llm_review_enabled": True,
        "context_review_enabled": True,
        "llm_endpoint": "https://llm.example.internal/v1",
        "llm_model": "qwen2.5-72b-instruct",
        "llm_api_key": "k",
        "llm_max_reviews": 20,
        "llm_timeout_seconds": 5,
        "context_max_files": 50,
        "pr_llm_enabled": False,
    }
    config.update(overrides)
    return config


def _run_pr_task(tmp_path, monkeypatch, config):
    repo = tmp_path / "repo"
    docs_dir = repo / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "quick-start.md").write_text("轮循", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    calls = []

    def record_post(url, headers=None, json=None, timeout=None):
        calls.append(json["messages"][0]["content"][:40])
        raise RuntimeError("no network in tests")

    monkeypatch.setattr("docsifter.llm_reviewer.requests.post", record_post)

    task_manager = GitHubTaskManager(FakeGitHub(repo))
    task_id = task_manager.create_github_task(
        "https://github.com/acme/docs",
        directories=[],
        check_all=False,
        pr_number=12,
        ref="abc123",
    )
    result = task_manager.execute_github_task(task_id, _pr_reviewer_with_config(config))
    return result, calls


def test_pr_review_skips_both_llm_layers_by_default(tmp_path, monkeypatch):
    # Both layers are on for CLI and Web, but the webhook path opts out.
    result, calls = _run_pr_task(tmp_path, monkeypatch, _llm_layers_config())

    assert result["success"] is True
    assert calls == []


def test_pr_review_runs_both_llm_layers_when_opted_in(tmp_path, monkeypatch):
    result, calls = _run_pr_task(tmp_path, monkeypatch, _llm_layers_config(pr_llm_enabled=True))

    # One context request for the file, one verdict request for the model finding.
    assert result["success"] is True
    assert len(calls) == 2

    # An endpoint that is down must not fail the pull request review.
    assert result["report_path"]


def test_pr_review_needs_the_layers_themselves_enabled(tmp_path, monkeypatch):
    # The gate opens the path; it does not turn the layers on by itself.
    _, calls = _run_pr_task(
        tmp_path,
        monkeypatch,
        _llm_layers_config(
            pr_llm_enabled=True, llm_review_enabled=False, context_review_enabled=False
        ),
    )

    assert calls == []


# --- email configuration validation and delivery limits -------------------------


def _email_service(tmp_path, **config):
    base = {
        "email_notifications_enabled": True,
        "email_smtp_server": "smtp.example.com",
        "email_smtp_port": 587,
        "email_username": "sender@example.com",
        "email_password": "secret",
        "email_sender": "sender@example.com",
        "email_recipients": ["docs@example.com"],
        "notify_on_error": True,
        "attach_report": True,
    }
    base.update(config)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(base), encoding="utf-8")
    return EmailNotificationService(ConfigManager(str(config_path))), config_path


def test_authentication_failure_is_not_retried(tmp_path):
    import smtplib

    service, _ = _email_service(tmp_path)
    attempts = []

    def failing_connection():
        attempts.append(1)
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    service._create_smtp_connection = failing_connection

    with pytest.raises(smtplib.SMTPAuthenticationError):
        service._send_email_with_retry(object())

    # Repeating a rejected login can get the account locked and never succeeds.
    assert len(attempts) == 1


def test_transient_failure_is_still_retried(tmp_path):
    service, _ = _email_service(tmp_path)
    attempts = []

    def flaky_connection():
        attempts.append(1)
        raise TimeoutError("connection timed out")

    service._create_smtp_connection = flaky_connection
    service.retry_delay = 0

    with pytest.raises(TimeoutError):
        service._send_email_with_retry(object())

    assert len(attempts) == service.max_retries


def test_notification_toggles_are_persisted(tmp_path):
    service, config_path = _email_service(tmp_path)

    # These keys carry no `email_` prefix; a prefix filter used to drop them, so
    # switching a notification off reported success and changed nothing.
    result = service.update_config(
        {"notify_on_error": False, "attach_report": False, "notify_on_local_complete": False}
    )

    assert result["success"] is True
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["notify_on_error"] is False
    assert persisted["attach_report"] is False
    assert persisted["notify_on_local_complete"] is False


def test_email_config_rejects_unusable_values(tmp_path):
    service, config_path = _email_service(tmp_path)

    assert service.update_config({"email_smtp_port": "not-a-number"})["success"] is False
    assert service.update_config({"email_smtp_port": 70000})["success"] is False
    assert service.update_config({"email_sender": "not-an-address"})["success"] is False
    assert (
        service.update_config({"email_recipients": ["a@b.com\nBcc: evil@x.com"]})["success"]
        is False
    )
    assert service.update_config({"unrelated_key": 1})["success"] is False

    # A rejected field must not leave the previous settings half-written.
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["email_smtp_port"] == 587
    assert persisted["email_sender"] == "sender@example.com"


def test_recipients_accept_a_separated_string(tmp_path):
    service, _ = _email_service(tmp_path)

    # A bare string used to be stored as-is and joined character by character.
    assert service.update_config({"email_recipients": "a@x.com, b@y.com"})["success"] is True
    assert service.recipient_emails == ["a@x.com", "b@y.com"]


def test_oversized_report_is_skipped_instead_of_failing_the_email(tmp_path):
    service, _ = _email_service(tmp_path, email_max_attachment_mb=1)
    report = tmp_path / "big.html"
    report.write_bytes(b"x" * (2 * 1024 * 1024))
    small = tmp_path / "small.html"
    small.write_bytes(b"x" * 1024)

    from email.mime.multipart import MIMEMultipart

    assert service._attach_report(MIMEMultipart(), str(report)) is False
    assert service._attach_report(MIMEMultipart(), str(small)) is True
