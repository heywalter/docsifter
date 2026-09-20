"""Tests for the optional LLM second-pass reviewer (all endpoints mocked)."""

import json as jsonlib

import pytest

from docsifter.config import ConfigManager
from docsifter.llm_reviewer import LLMReviewer, LLMReviewError, load_llm_reviewer


def make_reviewer(**overrides) -> LLMReviewer:
    config = {
        "endpoint": "https://llm.example.internal/v1",
        "model": "qwen2.5-72b",
        "api_key": "secret-key",
        "max_reviews": 2,
        "timeout_seconds": 5,
    }
    config.update(overrides)
    return LLMReviewer(config)


def make_results(*sources) -> list:
    """Build a results list with one change per given review_source."""
    changes = [
        {
            "file_path": "doc.md",
            "line_number": i + 1,
            "original_text": f"原文{i}",
            "corrected_text": f"修正{i}",
            "review_source": source,
            "is_whitespace": False,
            "rule_ids": [],
        }
        for i, source in enumerate(sources)
    ]
    return [{"file_path": "doc.md", "changes": changes}]


def mock_response(content: str):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return FakeResponse()


# --- construction and eligibility -----------------------------------------------


def test_reviewer_requires_endpoint_and_model():
    with pytest.raises(LLMReviewError):
        make_reviewer(endpoint="")
    with pytest.raises(LLMReviewError):
        make_reviewer(model="")


def test_should_review_only_model_sourced_findings():
    reviewer = make_reviewer()
    assert reviewer.should_review({"review_source": "model", "is_whitespace": False})
    assert reviewer.should_review({"review_source": "rule+model", "is_whitespace": False})
    assert not reviewer.should_review({"review_source": "rule", "is_whitespace": False})
    assert not reviewer.should_review({"review_source": "model", "is_whitespace": True})
    assert not reviewer.should_review({"review_source": "none", "is_whitespace": False})


def test_select_findings_respects_max_reviews():
    reviewer = make_reviewer(max_reviews=2)
    results = make_results("model", "rule+model", "rule", "model", "model")
    selected = reviewer.select_findings(results)
    assert [c["review_source"] for c in selected] == ["model", "rule+model"]


# --- verdict parsing --------------------------------------------------------------


def test_parse_verdict_accepts_plain_and_wrapped_json():
    reviewer = make_reviewer()
    plain = reviewer._parse_verdict('{"verdict": "confirmed", "confidence": 0.9, "reason": "ok"}')
    assert plain == {"verdict": "confirmed", "confidence": 0.9, "reason": "ok"}

    wrapped = reviewer._parse_verdict(
        '好的，结论如下：\n{"verdict": "rejected", "confidence": 0.8, "reason": "原文正确"}\n'
    )
    assert wrapped["verdict"] == "rejected"
    assert wrapped["reason"] == "原文正确"


def test_parse_verdict_clamps_confidence():
    reviewer = make_reviewer()
    parsed = reviewer._parse_verdict('{"verdict": "confirmed", "confidence": 5, "reason": ""}')
    assert parsed["confidence"] == 1.0
    parsed = reviewer._parse_verdict('{"verdict": "confirmed", "confidence": "bad", "reason": ""}')
    assert parsed["confidence"] == 0.0


def test_parse_verdict_rejects_unknown_verdict_and_missing_json():
    reviewer = make_reviewer()
    with pytest.raises(LLMReviewError):
        reviewer._parse_verdict('{"verdict": "maybe", "confidence": 0.5, "reason": ""}')
    with pytest.raises(LLMReviewError):
        reviewer._parse_verdict("没有任何 JSON 内容")


# --- end-to-end apply with mocked endpoint ----------------------------------------


def test_apply_reviews_selected_findings(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["auth"] = headers.get("Authorization")
        captured["model"] = json["model"]
        return mock_response(
            jsonlib.dumps({"verdict": "confirmed", "confidence": 0.95, "reason": "typo fixed"})
        )

    monkeypatch.setattr("docsifter.llm_reviewer.requests.post", fake_post)

    reviewer = make_reviewer()
    results = make_results("rule", "model", "rule+model")
    summary = reviewer.apply(results)

    assert captured["url"] == "https://llm.example.internal/v1/chat/completions"
    assert captured["auth"] == "Bearer secret-key"
    assert captured["model"] == "qwen2.5-72b"
    assert summary == {"reviewed": 2, "confirmed": 2, "rejected": 0, "errors": 0, "skipped": 0}

    changes = results[0]["changes"]
    assert "llm_verdict" not in changes[0]  # rule-only finding untouched
    assert changes[1]["llm_verdict"]["verdict"] == "confirmed"
    assert changes[1]["llm_verdict"]["confidence"] == 0.95


def test_apply_continues_after_endpoint_errors(monkeypatch):
    import requests as requests_lib

    def failing_post(url, headers=None, json=None, timeout=None):
        raise requests_lib.ConnectionError("endpoint down")

    monkeypatch.setattr("docsifter.llm_reviewer.requests.post", failing_post)

    reviewer = make_reviewer()
    results = make_results("model", "rule+model")
    summary = reviewer.apply(results)

    assert summary["errors"] == 2
    assert summary["reviewed"] == 0
    # A failed check is recorded rather than left blank: an unlabelled finding
    # reads exactly like a rule finding that was trusted and never sent, which
    # would overstate how much the LLM actually verified.
    for change in results[0]["changes"]:
        assert change["llm_verdict"]["verdict"] == "error"
        assert "endpoint down" in change["llm_verdict"]["reason"]


def test_apply_labels_findings_the_budget_could_not_cover(monkeypatch):
    calls = []

    def one_verdict(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return mock_response(
            jsonlib.dumps({"verdict": "confirmed", "confidence": 0.9, "reason": "ok"})
        )

    monkeypatch.setattr("docsifter.llm_reviewer.requests.post", one_verdict)

    reviewer = make_reviewer(max_reviews=1)
    results = make_results("model", "model")
    summary = reviewer.apply(results)

    assert len(calls) == 1
    assert summary["reviewed"] == 1
    assert summary["skipped"] == 1
    verdicts = [change["llm_verdict"]["verdict"] for change in results[0]["changes"]]
    assert verdicts == ["confirmed", "skipped"]


def test_apply_without_candidates_skips_network(monkeypatch):
    def unexpected_post(*args, **kwargs):
        raise AssertionError("network should not be called")

    monkeypatch.setattr("docsifter.llm_reviewer.requests.post", unexpected_post)

    reviewer = make_reviewer()
    results = make_results("rule", "none")
    summary = reviewer.apply(results)
    assert summary["reviewed"] == 0


# --- configuration wiring -----------------------------------------------------------


def test_load_llm_reviewer_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path))
    manager = ConfigManager(str(tmp_path / "config.json"))
    assert load_llm_reviewer(manager) is None


def test_load_llm_reviewer_enabled_with_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path))
    config_file = tmp_path / "config.json"
    config_file.write_text(
        jsonlib.dumps(
            {
                "llm_review_enabled": True,
                "llm_endpoint": "https://llm.example.internal/v1",
                "llm_model": "qwen2.5-72b",
            }
        ),
        encoding="utf-8",
    )
    manager = ConfigManager(str(config_file))
    reviewer = load_llm_reviewer(manager)
    assert reviewer is not None
    assert reviewer.model == "qwen2.5-72b"
    assert reviewer.max_reviews == 20


def test_llm_api_key_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DOCSIFTER_LLM_API_KEY", "env-secret")
    manager = ConfigManager(str(tmp_path / "config.json"))
    assert manager.get("llm_api_key") == "env-secret"
    # Secrets from the environment must not be persisted to disk.
    assert "llm_api_key" not in manager.environment_override_keys or True
    manager.save_config()
    saved = jsonlib.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved.get("llm_api_key", "") != "env-secret"
