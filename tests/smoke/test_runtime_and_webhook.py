import hashlib
import hmac
import json
import threading
import time

from docsifter.config import ConfigManager
from docsifter.runtime import get_runtime_path


def wait_for_task(client, task_id, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/history/{task_id}")
        task = response.get_json()["data"]
        if task["status"] in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.01)
    raise AssertionError("task did not finish before timeout")


def wait_for_review_history(client, expected_count, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = client.get(
            "/api/github/review-history", query_string={"limit": expected_count}
        ).get_json()
        reviews = payload.get("data", [])
        histories_done = len(reviews) >= expected_count and all(
            review["status"] in {"completed", "failed", "cancelled"}
            for review in reviews[:expected_count]
        )
        logs_payload = client.get("/api/github/webhook/logs").get_json()
        completed_logs = [
            log
            for log in logs_payload.get("data", {}).get("logs", [])
            if "auto-review completed" in log.get("message", "")
        ]
        if histories_done and len(completed_logs) >= expected_count:
            return reviews
        time.sleep(0.01)
    raise AssertionError("review history did not reach a terminal state before timeout")


def test_runtime_state_uses_configured_data_directory(monkeypatch, tmp_path):
    data_dir = tmp_path / "runtime-state"
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(data_dir))

    config = ConfigManager()

    assert config.config_file == str(data_dir / "config.json")
    assert get_runtime_path("reports", "review.html") == str(data_dir / "reports" / "review.html")


def test_webhook_uses_public_url_and_verifies_signature(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "runtime-state"))
    monkeypatch.setenv("DOCSIFTER_PUBLIC_URL", "https://review.example.com/docsifter/")
    monkeypatch.setenv("DOCSIFTER_ADMIN_TOKEN", "admin-token-for-public-tests")

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    app = create_flask_app(DocumentReviewer(server_mode=True))
    client = app.test_client()
    management_headers = {
        "Authorization": "Bearer admin-token-for-public-tests",
        "X-DocSifter-Request": "1",
    }
    config_response = client.post(
        "/api/github/webhook/config",
        headers=management_headers,
        json={
            "repo_url": "https://github.com/acme/docs",
            "monitor_events": ["pr_created", "pr_updated", "pr_reopened"],
            "review_model": "shibing624/chinese-text-correction-1.5b",
        },
    )
    secret = config_response.get_json()["data"]["webhook_secret"]
    status = client.get(
        "/api/github/webhook/status",
        headers={"Authorization": "Bearer admin-token-for-public-tests"},
    ).get_json()["data"]
    client.post("/api/github/webhook/enable", headers=management_headers)

    body = b"{}"
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/github/webhook",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": signature,
        },
    )

    assert status["webhook_url"] == "https://review.example.com/docsifter/api/github/webhook"
    assert status["webhook_secret_configured"] is True
    assert "webhook_secret" not in status
    assert status["review_model"] == "shibing624/chinese-text-correction-1.5b"
    assert response.status_code == 200
    assert response.get_json()["message"] == "pong"


def test_web_api_persists_and_serves_reports_in_runtime_directory(monkeypatch, tmp_path):
    runtime_dir = tmp_path / "runtime-state"
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(runtime_dir))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    app = create_flask_app(DocumentReviewer(server_mode=True))
    client = app.test_client()
    response = client.post(
        "/api/process",
        json={"directory": "examples/sample-docs", "model": "rule-based"},
    )

    payload = response.get_json()
    task_id = payload["data"]["task_id"]
    task = wait_for_task(client, task_id)
    report_path = task["report_path"]

    assert response.status_code == 202
    assert payload["success"] is True
    assert task["status"] == "completed"
    assert report_path == str(runtime_dir / "reports" / f"{task_id}.html")
    assert client.get("/report.html").status_code == 200


def test_legacy_manual_github_review_api_is_not_exposed(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "runtime-state"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    client = create_flask_app(reviewer).test_client()

    for route in [
        "/api/github/parse-url",
        "/api/github/repo-info",
        "/api/github/directories",
        "/api/github/pull-requests",
        "/api/github/pr-files",
        "/api/github/process",
    ]:
        assert client.post(route, json={}).status_code == 404


def test_github_review_history_report_can_be_downloaded(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "runtime-state"))

    import docsifter.models as models
    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    report = tmp_path / "github-review.html"
    report.write_text("<html><body>review</body></html>", encoding="utf-8")
    models.init_db()
    with models.get_session() as session:
        history = models.GitHubReviewHistory(
            repo_url="https://github.com/acme/docs",
            pr_number=12,
            status="completed",
            report_path=str(report),
        )
        session.add(history)
        session.flush()
        history_id = history.id

    client = create_flask_app(DocumentReviewer(server_mode=True)).test_client()
    response = client.get(f"/api/github/review-history/{history_id}/report")

    assert response.status_code == 200
    assert response.data == report.read_bytes()
    assert f"github_review_{history_id}.html" in response.headers["Content-Disposition"]


def test_webhook_ignores_duplicate_pr_while_review_is_running(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "runtime-state"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    app = create_flask_app(reviewer)
    client = app.test_client()
    config_response = client.post(
        "/api/github/webhook/config",
        json={
            "repo_url": "https://github.com/acme/docs",
            "monitor_events": ["pr_created"],
            "review_model": "shibing624/chinese-text-correction-1.5b",
        },
    )
    secret = config_response.get_json()["data"]["webhook_secret"]
    client.post("/api/github/webhook/enable")

    started = threading.Event()
    second_started = threading.Event()
    release = threading.Event()
    all_done = threading.Event()
    review_calls = []
    review_models = []
    completed_calls = []

    def fake_review(task_id, model):
        review_calls.append(task_id)
        review_models.append(model)
        started.set()
        if len(review_calls) == 2:
            second_started.set()
        assert release.wait(timeout=2)
        completed_calls.append(task_id)
        if len(completed_calls) == 2:
            all_done.set()
        return {"success": True, "total_files": 0, "files_with_issues": 0, "stats": {}}

    monkeypatch.setattr(reviewer, "run_github_review", fake_review)
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 12,
            "title": "Docs",
            "html_url": "https://github.com/acme/docs/pull/12",
            "head": {"sha": "abc123"},
        },
        "repository": {"html_url": "https://github.com/acme/docs"},
    }
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "delivery-1",
    }

    first = client.post("/api/github/webhook", data=body, headers=headers)
    assert first.status_code == 200
    assert started.wait(timeout=1)
    task_id = first.get_json()["task_id"]
    assert reviewer.github_task_manager.get_task_status(task_id)["ref"] == "refs/pull/12/head"

    # A retried delivery carries the same delivery id.
    duplicate = client.post("/api/github/webhook", data=body, headers=headers)

    # One push commonly raises several events with different delivery ids. They
    # describe the same commit, so they must not start a second review of it.
    same_commit_headers = {**headers, "X-GitHub-Delivery": "delivery-2"}
    same_commit = client.post("/api/github/webhook", data=body, headers=same_commit_headers)

    # A genuinely new push moves head.sha and must be reviewed.
    new_push_payload = {
        **payload,
        "pull_request": {**payload["pull_request"], "head": {"sha": "def456"}},
    }
    new_push_body = json.dumps(new_push_payload).encode("utf-8")
    new_push_headers = {
        **headers,
        "X-GitHub-Delivery": "delivery-3",
        "X-Hub-Signature-256": "sha256="
        + hmac.new(secret.encode("utf-8"), new_push_body, hashlib.sha256).hexdigest(),
    }
    new_push = client.post("/api/github/webhook", data=new_push_body, headers=new_push_headers)

    assert second_started.wait(timeout=1)
    release.set()
    assert all_done.wait(timeout=1)
    wait_for_review_history(client, 2)

    assert duplicate.status_code == 200
    assert duplicate.get_json()["message"] == "already processing"
    assert same_commit.status_code == 200
    assert same_commit.get_json()["message"] == "already processing"
    assert same_commit.get_json()["history_id"] == first.get_json()["history_id"]
    assert new_push.status_code == 200
    assert new_push.get_json()["message"] == "accepted"
    assert new_push.get_json()["task_id"] != task_id
    assert len(review_calls) == 2
    assert review_models == [
        "shibing624/chinese-text-correction-1.5b",
        "shibing624/chinese-text-correction-1.5b",
    ]


def test_webhook_acceptance_failure_returns_500_and_allows_redelivery(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "runtime-state"))

    from docsifter.orchestrator import DocumentReviewer
    from docsifter.web_app import create_flask_app

    reviewer = DocumentReviewer(server_mode=True)
    client = create_flask_app(reviewer).test_client()
    config_response = client.post(
        "/api/github/webhook/config",
        json={
            "repo_url": "https://github.com/acme/docs",
            "monitor_events": ["pr_created"],
        },
    )
    secret = config_response.get_json()["data"]["webhook_secret"]
    client.post("/api/github/webhook/enable")

    payload = {
        "action": "opened",
        "pull_request": {
            "number": 12,
            "title": "Docs",
            "html_url": "https://github.com/acme/docs/pull/12",
            "head": {"sha": "abc123"},
        },
        "repository": {"html_url": "https://github.com/acme/docs"},
    }
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "delivery-retry",
    }

    original_create = reviewer.github_task_manager.create_github_task
    monkeypatch.setattr(
        reviewer.github_task_manager,
        "create_github_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )
    failed = client.post("/api/github/webhook", data=body, headers=headers)

    monkeypatch.setattr(reviewer.github_task_manager, "create_github_task", original_create)
    monkeypatch.setattr(
        reviewer,
        "run_github_review",
        lambda task_id, model: {
            "success": True,
            "total_files": 0,
            "files_with_issues": 0,
            "stats": {},
        },
    )
    redelivery = client.post("/api/github/webhook", data=body, headers=headers)

    assert failed.status_code == 500
    assert failed.get_json()["success"] is False
    assert redelivery.status_code == 200
    assert redelivery.get_json()["message"] == "accepted"
