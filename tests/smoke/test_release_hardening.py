import base64
import json
import logging
import sys
import time
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest

import docsifter
from docsifter.history_manager import HistoryManager, TaskStatus

PACKAGE_DIR = Path(docsifter.__file__).resolve().parent


def basic_auth_headers(token: str, *, csrf: bool = False):
    encoded = base64.b64encode(f"docsifter:{token}".encode()).decode("ascii")
    headers = {"Authorization": f"Basic {encoded}"}
    if csrf:
        headers["X-DocSifter-Request"] = "1"
    return headers


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_local_review_api_runs_in_background_and_can_be_cancelled(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)

    def fake_review(directory, debug, task_id, model, auto_generate):
        wait_for(lambda: reviewer.history_manager.is_task_cancelled(task_id))
        return {"cancelled": True, "stats": {}, "results": []}

    monkeypatch.setattr(reviewer, "run_local_review", fake_review)
    client = create_flask_app(reviewer).test_client()

    response = client.post("/api/process", json={"directory": str(docs)})

    assert response.status_code == 202
    task_id = response.get_json()["data"]["task_id"]
    cancel_response = client.post("/api/cancel_task", json={"task_id": task_id})

    assert cancel_response.status_code == 200
    detail = wait_for(
        lambda: (
            task
            if (task := reviewer.history_manager.get_task_detail(task_id))["status"] == "cancelled"
            else None
        )
    )
    assert detail["error_message"] == "Cancelled by user"


def test_local_review_failure_updates_status_and_sends_error_notice(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()

    import docsifter.web.routes_review as routes_review
    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    notified = []

    class FakeEmailService:
        def send_error_notification(self, task_id, error_message, task_info):
            notified.append((task_id, error_message, task_info["status"]))
            return {"success": True, "message": "sent"}

    def fail_review(*args, **kwargs):
        raise RuntimeError("model failed")

    monkeypatch.setattr(reviewer, "run_local_review", fail_review)
    monkeypatch.setattr(routes_review, "get_email_service", lambda config: FakeEmailService())
    client = create_flask_app(reviewer).test_client()

    response = client.post("/api/process", json={"directory": str(docs)})
    task_id = response.get_json()["data"]["task_id"]
    detail = wait_for(
        lambda: (
            task
            if (task := reviewer.history_manager.get_task_detail(task_id))["status"] == "failed"
            else None
        )
    )

    assert detail["error_message"] == "model failed"
    assert wait_for(lambda: notified)
    assert notified[0] == (task_id, "model failed", "failed")


def test_explicit_model_request_fails_when_runtime_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()

    import docsifter.corrector as corrector
    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    monkeypatch.setattr(corrector, "load_gpt_corrector", lambda: False)
    reviewer = DocumentReviewer(server_mode=True)
    client = create_flask_app(reviewer).test_client()

    response = client.post(
        "/api/process",
        json={
            "directory": str(docs),
            "model": "shibing624/chinese-text-correction-1.5b",
        },
    )
    task_id = response.get_json()["data"]["task_id"]
    detail = wait_for(
        lambda: (
            task
            if (task := reviewer.history_manager.get_task_detail(task_id))["status"] == "failed"
            else None
        )
    )

    assert response.status_code == 202
    assert "docsifter[model]" in detail["error_message"]
    model_status = client.get("/api/model/status").get_json()["data"]
    assert model_status["model_loaded"] is False
    assert "docsifter[model]" in model_status["model_error"]


def test_github_model_failure_marks_active_task_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    import docsifter.corrector as corrector
    from docsifter.corrector import ModelUnavailableError
    from docsifter.orchestrator import DocumentReviewer

    monkeypatch.setattr(corrector, "load_gpt_corrector", lambda: False)
    reviewer = DocumentReviewer(server_mode=True)
    task_id = reviewer.github_task_manager.create_github_task(
        "https://github.com/acme/docs", [], False
    )

    with pytest.raises(ModelUnavailableError):
        reviewer.run_github_review(task_id, "shibing624/chinese-text-correction-1.5b")

    task = reviewer.github_task_manager.get_task_status(task_id)
    assert task["status"] == "failed"
    assert "docsifter[model]" in task["error"]


def test_history_manager_recovers_interrupted_tasks(tmp_path):
    history = HistoryManager(str(tmp_path / "history.db"))
    task_id = history.create_task("docs")
    history.update_task_status(task_id, TaskStatus.RUNNING)

    recovered = history.recover_interrupted_tasks()

    assert recovered == [task_id]
    detail = history.get_task_detail(task_id)
    assert detail["status"] == "failed"
    assert "service restart" in detail["error_message"].lower()


def test_history_manager_does_not_cancel_completed_task(tmp_path):
    history = HistoryManager(str(tmp_path / "history.db"))
    task_id = history.create_task("docs")
    history.update_task_status(task_id, TaskStatus.COMPLETED)

    assert history.cancel_task(task_id) is False
    assert history.get_task_detail(task_id)["status"] == "completed"


def test_github_history_recovers_interrupted_reviews(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    import docsifter.models as models

    models.init_db()
    with models.get_session() as session:
        review = models.GitHubReviewHistory(
            repo_url="https://github.com/acme/docs",
            pr_number=12,
            status="processing",
        )
        session.add(review)
        session.flush()
        review_id = review.id

    recovered = models.recover_interrupted_reviews()

    assert recovered == [review_id]
    with models.get_session() as session:
        review = session.query(models.GitHubReviewHistory).filter_by(id=review_id).one()
        assert review.status == "failed"
        assert "service restart" in review.error_message.lower()


def test_config_api_redacts_secrets_and_rejects_sensitive_updates(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFTER_GITHUB_TOKEN", "top-secret")
    monkeypatch.setenv("DOCSIFTER_EMAIL_PASSWORD", "smtp-secret")
    monkeypatch.setenv("DOCSIFTER_LLM_API_KEY", "llm-secret")
    monkeypatch.setenv("DOCSIFTER_OPENAI_API_KEY", "backend-secret")
    monkeypatch.chdir(tmp_path)

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    client = create_flask_app(reviewer).test_client()

    public_config = client.get("/config").get_json()
    update = client.post("/config", json={"github_token": "replacement"})

    assert "github_token" not in public_config
    assert "email_password" not in public_config
    assert "llm_api_key" not in public_config
    assert "openai_api_key" not in public_config
    assert update.status_code == 400
    assert reviewer.config["github_token"] == "top-secret"
    assert reviewer.config["llm_api_key"] == "llm-secret"
    assert reviewer.config["openai_api_key"] == "backend-secret"

    reviewer.update_config("whitelist", ["DocSifter"])
    persisted = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert "github_token" not in persisted
    assert "email_password" not in persisted
    assert "llm_api_key" not in persisted
    assert "openai_api_key" not in persisted


def test_web_responses_include_baseline_security_headers(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    response = create_flask_app(DocumentReviewer(server_mode=True)).test_client().get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_web_directory_access_is_limited_to_allowed_roots(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    client = create_flask_app(DocumentReviewer(server_mode=True)).test_client()

    assert client.get("/api/directories", query_string={"path": str(workspace)}).status_code == 200
    assert client.get("/api/directories", query_string={"path": str(outside)}).status_code == 403
    assert client.post("/api/process", json={"directory": str(outside)}).status_code == 403
    assert (
        client.post(
            "/api/process",
            json={"directory": str(workspace), "model": "untrusted/huge-model"},
        ).status_code
        == 400
    )


def test_whitelist_updates_runtime_config_without_rewriting_seed(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(data_dir))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    seed_path = PACKAGE_DIR / "whitelist.json"
    seed_before = seed_path.read_text(encoding="utf-8")
    reviewer = DocumentReviewer(server_mode=True)
    client = create_flask_app(reviewer).test_client()

    response = client.post("/api/whitelist", json={"whitelist": ["DocSifter", "API"]})

    assert response.status_code == 200
    assert seed_path.read_text(encoding="utf-8") == seed_before
    saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert saved["whitelist"] == ["DocSifter", "API"]
    assert client.get("/api/whitelist").get_json()["data"] == ["DocSifter", "API"]


def test_generated_report_escapes_untrusted_paths_and_avoids_inline_handlers(tmp_path):
    from docsifter.html_generator import HTMLGenerator
    from docsifter.html_template import HTMLTemplate

    malicious_path = tmp_path / "<img src=x onerror=alert(1)>.md"
    results = [
        {
            "file": str(malicious_path),
            "lines": [
                {
                    "original": 'x");alert(2);//',
                    "corrected": "y",
                    "review_source": "rule",
                    "severity": "warning",
                    "rule_ids": [],
                }
            ],
            "line_map": [1],
        }
    ]

    content = HTMLGenerator(str(tmp_path))._generate_files_content(results)

    assert "<img src=x" not in content
    assert "&lt;img src=x onerror=alert(1)&gt;.md" in content
    assert "onclick=" not in content
    assert 'data-fp-action="mark"' in content
    assert "<img src=x" not in HTMLTemplate().generate_hero_section("<img src=x onerror=alert(3)>")


def test_generated_report_is_self_contained():
    from docsifter.html_template import HTMLTemplate

    report = HTMLTemplate().generate_full_html(
        {
            "total_files": 0,
            "valid_changes": 0,
            "total_changes": 0,
            "total_whitespace_changes": 0,
            "total_chars": 0,
            "defect_rate_per_thousand": 0,
        },
        "",
        "rule-based",
    )

    assert "fonts.googleapis.com" not in report
    assert "fonts.gstatic.com" not in report
    assert "onclick=" not in report
    assert "fetch('/api/false_positives'" in report
    assert "/mark_false_positive" not in report
    assert "/unmark_false_positive" not in report
    assert "window.location.protocol === 'file:'" in report


def test_public_url_requires_admin_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFTER_PUBLIC_URL", "https://review.example.com")

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    with pytest.raises(RuntimeError, match="DOCSIFTER_ADMIN_TOKEN"):
        create_flask_app(DocumentReviewer(server_mode=True))

    monkeypatch.setenv("DOCSIFTER_ADMIN_TOKEN", "too-short")
    with pytest.raises(RuntimeError, match="at least 24"):
        create_flask_app(DocumentReviewer(server_mode=True))


def test_non_loopback_server_bind_requires_a_strong_admin_token(monkeypatch):
    from docsifter.web_app import validate_server_bind

    monkeypatch.delenv("DOCSIFTER_ADMIN_TOKEN", raising=False)
    validate_server_bind("127.0.0.1")
    validate_server_bind("::1")
    validate_server_bind("localhost")

    with pytest.raises(RuntimeError, match="DOCSIFTER_ADMIN_TOKEN"):
        validate_server_bind("0.0.0.0")

    monkeypatch.setenv("DOCSIFTER_ADMIN_TOKEN", "too-short")
    with pytest.raises(RuntimeError, match="at least 24"):
        validate_server_bind("0.0.0.0")

    monkeypatch.setenv("DOCSIFTER_ADMIN_TOKEN", "a-secure-token-with-24-chars")
    validate_server_bind("0.0.0.0")


def test_admin_token_protects_management_routes_and_mutations(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFTER_ADMIN_TOKEN", "test-admin-token")

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    client = create_flask_app(DocumentReviewer(server_mode=True)).test_client()
    auth = basic_auth_headers("test-admin-token")

    assert client.get("/config").status_code == 401
    assert client.get("/config", headers=auth).status_code == 200
    assert client.post("/config", headers=auth, json={"whitelist": ["API"]}).status_code == 403
    assert (
        client.post(
            "/config",
            headers=basic_auth_headers("test-admin-token", csrf=True),
            json={"whitelist": ["API"]},
        ).status_code
        == 200
    )


def test_local_history_api_reports_real_pagination(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    for index in range(12):
        reviewer.history_manager.create_task(f"docs-{index}")

    payload = (
        create_flask_app(reviewer)
        .test_client()
        .get("/api/history", query_string={"page": 1, "page_size": 10})
        .get_json()["data"]
    )

    assert len(payload["tasks"]) == 10
    assert payload["pagination"]["total_count"] == 12
    assert payload["pagination"]["total_pages"] == 2


def test_total_stats_do_not_scale_per_thousand_rate_twice(tmp_path):
    from docsifter.history_manager import HistoryManager, TaskStatus

    history = HistoryManager(str(tmp_path / "history.db"))
    task_id = history.create_task("docs")
    history.update_task_stats(
        task_id,
        {
            "total_files": 1,
            "valid_changes": 2,
            "total_chars": 800,
            "defect_rate_per_thousand": 2.5,
        },
    )
    history.update_task_status(task_id, TaskStatus.COMPLETED)

    assert history.get_total_stats()["defect_rate_per_thousand"] == 2.5


def test_total_changes_include_findings_filtered_as_false_positives(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.orchestrator import DocumentReviewer

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("请登陆帐户。", encoding="utf-8")
    reviewer = DocumentReviewer(server_mode=True)
    reviewer.false_positive_manager.add_false_positive("请登陆帐户。", "请登录账户。")

    stats = reviewer.process_directory(str(docs))["stats"]

    assert stats["total_changes"] == 1
    assert stats["valid_changes"] == 0


def test_web_template_has_unique_element_ids():
    class IdCollector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []

        def handle_starttag(self, _tag, attrs):
            self.ids.extend(value for name, value in attrs if name == "id")

    parser = IdCollector()
    parser.feed((PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8"))

    duplicates = sorted(
        element_id for element_id, count in Counter(parser.ids).items() if count > 1
    )
    assert duplicates == []


def test_local_progress_api_returns_the_full_progress_history(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    task_id = reviewer.history_manager.create_task("docs")
    reviewer.history_manager.update_progress(task_id, 10, message="Started")
    reviewer.history_manager.update_progress(
        task_id, 80, current_file="guide.md", message="Reviewing"
    )

    payload = (
        create_flask_app(reviewer).test_client().get(f"/api/history/{task_id}/progress").get_json()
    )

    assert payload["success"] is True
    assert [item["progress"] for item in payload["data"]] == [10, 80]
    assert payload["data"][1]["current_file"] == "guide.md"


def test_false_positive_import_and_batch_delete_match_the_web_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    client = create_flask_app(DocumentReviewer(server_mode=True)).test_client()
    first_item = {
        "original": "api_name_旧",
        "corrected": "api_name_新",
        "is_pattern": False,
        "note": "Keep the product context",
    }

    assert client.post("/api/false_positives", json=first_item).status_code == 200
    imported = client.post(
        "/api/false_positives/import",
        json={
            "false_positives": [
                first_item,
                {
                    "original": "^internal_[a-z]+$",
                    "corrected": "",
                    "is_pattern": True,
                    "note": "Internal identifier",
                },
            ]
        },
    )

    assert imported.status_code == 200
    assert imported.get_json()["imported_count"] == 1
    items = client.get("/api/false_positives").get_json()["data"]
    assert len(items) == 2
    assert items[0]["note"] == "Keep the product context"

    deleted = client.delete("/api/false_positives/batch", json={"items": [first_item]})

    assert deleted.status_code == 200
    assert deleted.get_json()["removed_count"] == 1
    remaining = client.get("/api/false_positives").get_json()["data"]
    assert [item["original"] for item in remaining] == ["^internal_[a-z]+$"]


def test_false_positive_ui_uses_structured_item_identity():
    app_js = (PACKAGE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert "falsePositiveItemId(item)" in app_js
    assert "itemId.split('_')" not in app_js
    assert "'/api/false_positives/batch'" in app_js
    assert "'/api/false_positives/import'" in app_js


def test_compose_forwards_documented_email_environment_variables():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    variables = [
        "DOCSIFTER_EMAIL_SMTP_SERVER",
        "DOCSIFTER_EMAIL_SMTP_PORT",
        "DOCSIFTER_EMAIL_USERNAME",
        "DOCSIFTER_EMAIL_PASSWORD",
        "DOCSIFTER_EMAIL_SENDER",
        "DOCSIFTER_EMAIL_RECIPIENTS",
        "DOCSIFTER_EMAIL_NOTIFICATIONS_ENABLED",
    ]

    for variable in variables:
        assert f"{variable}: ${{{variable}:-" in compose
        assert f"{variable}=" in env_example

    assert "DOCSIFTER_INSTALL_MODEL_RUNTIME=" in env_example


# --- Web LLM configuration panel -----------------------------------------------


def _llm_client(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    return reviewer, create_flask_app(reviewer).test_client()


def test_llm_config_endpoint_never_returns_the_api_key(monkeypatch, tmp_path):
    reviewer, client = _llm_client(monkeypatch, tmp_path, DOCSIFTER_LLM_API_KEY="llm-secret")

    payload = client.get("/api/llm/config").get_json()

    assert reviewer.config["llm_api_key"] == "llm-secret"
    assert "llm_api_key" not in payload
    assert payload["api_key_configured"] is True
    assert "llm_api_key" in payload["environment_locked"]


def test_llm_config_rejects_changes_pinned_by_environment(monkeypatch, tmp_path):
    reviewer, client = _llm_client(
        monkeypatch, tmp_path, DOCSIFTER_LLM_ENDPOINT="https://pinned.example.com/v1"
    )

    response = client.post("/api/llm/config", json={"llm_endpoint": "https://attacker.example"})

    assert response.status_code == 409
    assert reviewer.config["llm_endpoint"] == "https://pinned.example.com/v1"


def test_llm_api_key_from_web_is_never_written_to_disk(monkeypatch, tmp_path):
    reviewer, client = _llm_client(monkeypatch, tmp_path)

    response = client.post(
        "/api/llm/config",
        json={
            "llm_endpoint": "https://llm.example.internal/v1",
            "llm_model": "qwen2.5-72b-instruct",
            "llm_api_key": "typed-in-the-browser",
            "llm_review_enabled": True,
        },
    )

    assert response.status_code == 200
    assert reviewer.config["llm_api_key"] == "typed-in-the-browser"
    persisted = json.loads((tmp_path / "data" / "config.json").read_text(encoding="utf-8"))
    assert "llm_api_key" not in persisted
    assert persisted["llm_endpoint"] == "https://llm.example.internal/v1"
    assert persisted["llm_review_enabled"] is True
    # Typing a key in the browser must not make it look environment-pinned.
    assert "llm_api_key" not in client.get("/api/llm/config").get_json()["environment_locked"]


def test_llm_config_refuses_to_enable_a_layer_with_no_endpoint(monkeypatch, tmp_path):
    reviewer, client = _llm_client(monkeypatch, tmp_path)

    response = client.post("/api/llm/config", json={"context_review_enabled": True})

    assert response.status_code == 400
    assert reviewer.config["context_review_enabled"] is False


def test_llm_config_validates_endpoint_scheme_and_numeric_bounds(monkeypatch, tmp_path):
    _, client = _llm_client(monkeypatch, tmp_path)

    assert client.post("/api/llm/config", json={"llm_endpoint": "ftp://x/v1"}).status_code == 400
    assert client.post("/api/llm/config", json={"llm_max_reviews": 0}).status_code == 400
    assert client.post("/api/llm/config", json={"context_max_files": "many"}).status_code == 400
    assert client.post("/api/llm/config", json={"llm_timeout_seconds": 9999}).status_code == 400
    assert client.post("/api/llm/config", json={"whitelist": []}).status_code == 400


def test_pr_llm_toggle_does_not_require_an_endpoint_of_its_own(monkeypatch, tmp_path):
    reviewer, client = _llm_client(monkeypatch, tmp_path)

    # It gates the two layers rather than being one, so it carries no endpoint
    # requirement; the layers it gates enforce that themselves.
    response = client.post("/api/llm/config", json={"pr_llm_enabled": True})

    assert response.status_code == 200
    assert reviewer.config["pr_llm_enabled"] is True
    assert client.get("/api/llm/config").get_json()["pr_llm_enabled"] is True


def test_pr_llm_defaults_off_so_webhook_reviews_stay_local(monkeypatch, tmp_path):
    reviewer, client = _llm_client(
        monkeypatch,
        tmp_path,
        DOCSIFTER_LLM_REVIEW_ENABLED="true",
        DOCSIFTER_CONTEXT_REVIEW_ENABLED="true",
        DOCSIFTER_LLM_ENDPOINT="https://llm.example.internal/v1",
        DOCSIFTER_LLM_MODEL="qwen2.5-72b-instruct",
    )

    # Both layers on for CLI/Web, but an unattended webhook review still opts out.
    assert reviewer.config["llm_review_enabled"] is True
    assert reviewer.config["context_review_enabled"] is True
    assert reviewer.config["pr_llm_enabled"] is False
    assert client.get("/api/llm/config").get_json()["pr_llm_enabled"] is False


def test_pr_llm_can_be_pinned_by_environment(monkeypatch, tmp_path):
    reviewer, client = _llm_client(monkeypatch, tmp_path, DOCSIFTER_PR_LLM_ENABLED="true")

    assert reviewer.config["pr_llm_enabled"] is True
    payload = client.get("/api/llm/config").get_json()
    assert "pr_llm_enabled" in payload["environment_locked"]
    assert client.post("/api/llm/config", json={"pr_llm_enabled": False}).status_code == 409


def test_unexpected_errors_do_not_echo_internals_to_the_client(monkeypatch, tmp_path, caplog):
    """An unexpected exception is logged, not handed back over HTTP.

    The Web UI may be reached over a network behind an administrator token, and
    exception text routinely carries filesystem paths and database locations.
    """
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    secret = "/srv/internal/customer-manuals/history.db"

    def explode(*args, **kwargs):
        raise RuntimeError(f"unable to open database file: {secret}")

    monkeypatch.setattr(reviewer.history_manager, "get_task_history", explode)
    client = create_flask_app(reviewer).test_client()

    with caplog.at_level(logging.ERROR):
        response = client.get("/api/history")

    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert secret not in body
    assert response.get_json() == {"success": False, "message": "Internal server error"}
    # The operator still gets the detail, in the log.
    assert secret in caplog.text


@pytest.mark.parametrize(
    "entry_point, argv",
    [
        ("docsifter.start_web", ["docsifter-web", "--host", "0.0.0.0", "--no-browser"]),
        ("docsifter.cli", ["docsifter", ".", "--server", "--host", "0.0.0.0"]),
    ],
)
def test_a_refused_bind_is_reported_without_a_traceback(
    monkeypatch, tmp_path, capsys, caplog, entry_point, argv
):
    """The remedy is in the message, so it must not be buried in a traceback."""
    import importlib

    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DOCSIFTER_ADMIN_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    module = importlib.import_module(entry_point)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 1
    reported = capsys.readouterr().err + caplog.text
    assert "DOCSIFTER_ADMIN_TOKEN" in reported
    assert "Traceback" not in reported
