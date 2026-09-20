"""Tests for the pluggable correction backends (transformers/Ollama/OpenAI-compatible)."""

import pytest
import requests

from docsifter.config import ConfigManager
from docsifter.corrector import (
    SUPPORTED_MODEL_BACKENDS,
    ModelExecutionError,
    ModelUnavailableError,
    OllamaBackend,
    OpenAICompatibleBackend,
    TextCorrector,
)
from docsifter.orchestrator import WEB_ALLOWED_MODELS, is_model_allowed

RECOMMENDED_MODEL = "shibing624/chinese-text-correction-1.5b"


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def make_config(tmp_path, **overrides) -> dict:
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    config.update(overrides)
    return config


# --- backend selection --------------------------------------------------------------


def test_text_corrector_rejects_unknown_backend(tmp_path):
    config = make_config(tmp_path, model_backend="bogus")
    with pytest.raises(ValueError, match="Unsupported model backend"):
        TextCorrector(config, server_mode=True)


def test_supported_backends_are_declared():
    assert SUPPORTED_MODEL_BACKENDS == ("local", "ollama", "openai")


def test_ollama_backend_is_selected_from_config(tmp_path):
    config = make_config(tmp_path, model_backend="ollama", ai_correction_enabled=True)
    corrector = TextCorrector(config)

    assert corrector.backend_kind == "ollama"
    assert isinstance(corrector.gpt_client, OllamaBackend)
    assert corrector.gpt_client.model_name == RECOMMENDED_MODEL
    assert corrector.gpt_client.base_url == "http://127.0.0.1:11434"


def test_openai_backend_is_selected_from_config(tmp_path):
    config = make_config(
        tmp_path,
        model_backend="openai",
        ai_correction_enabled=True,
        openai_base_url="https://llm.example.internal/v1",
        openai_api_key="secret-key",
    )
    corrector = TextCorrector(config)

    assert isinstance(corrector.gpt_client, OpenAICompatibleBackend)
    assert corrector.gpt_client.base_url == "https://llm.example.internal/v1"


# --- remote correction calls --------------------------------------------------------


def test_ollama_backend_corrects_text(monkeypatch, tmp_path):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": json})
        return FakeResponse({"message": {"content": "这是一段测试文档。"}})

    monkeypatch.setattr(requests, "post", fake_post)
    config = make_config(tmp_path, model_backend="ollama", ai_correction_enabled=True)
    corrector = TextCorrector(config)

    corrected = corrector.correct_text("这是一段测试文挡。")

    assert corrected == "这是一段测试文档。"
    assert calls[0]["url"].endswith("/api/chat")
    assert calls[0]["payload"]["model"] == RECOMMENDED_MODEL
    assert calls[0]["payload"]["stream"] is False
    assert "__URL_0__" in calls[0]["payload"]["messages"][0]["content"]


def test_openai_backend_sends_bearer_token_and_corrects(monkeypatch, tmp_path):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "payload": json})
        return FakeResponse({"choices": [{"message": {"content": "这是一段测试文档。"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    config = make_config(
        tmp_path,
        model_backend="openai",
        ai_correction_enabled=True,
        openai_base_url="https://llm.example.internal/v1",
        openai_api_key="secret-key",
    )
    corrector = TextCorrector(config)

    corrected, metadata = corrector.correct_text_with_metadata("这是一段测试文挡。")

    assert corrected == "这是一段测试文档。"
    assert metadata["review_source"] == "model"
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert calls[0]["payload"]["model"] == RECOMMENDED_MODEL


def test_remote_backend_failure_raises_model_execution_error(monkeypatch, tmp_path):
    def failing_post(url, json=None, timeout=None):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", failing_post)
    config = make_config(tmp_path, model_backend="ollama", ai_correction_enabled=True)
    corrector = TextCorrector(config)

    with pytest.raises(ModelExecutionError, match="Ollama request failed"):
        corrector.correct_text("这是一段测试文挡。")


def test_openai_backend_requires_base_url(tmp_path):
    config = make_config(tmp_path, model_backend="openai", server_mode=True)
    corrector = TextCorrector(config, server_mode=True)
    corrector.ai_correction_enabled = True

    with pytest.raises(ModelUnavailableError, match="base URL"):
        corrector.update_model("gpt-4o-mini")


# --- model allowlist behaviour ------------------------------------------------------


def test_local_backend_limits_models_to_the_curated_list():
    class StubCorrector:
        backend_kind = "local"

    assert is_model_allowed(StubCorrector(), "rule-based")
    assert is_model_allowed(StubCorrector(), RECOMMENDED_MODEL)
    assert not is_model_allowed(StubCorrector(), "gpt-4o-mini")
    assert WEB_ALLOWED_MODELS == {
        "rule-based",
        RECOMMENDED_MODEL,
        "shibing624/chinese-text-correction-7b",
    }


def test_remote_backend_accepts_any_model_name():
    for kind in ("ollama", "openai"):

        class StubCorrector:
            backend_kind = kind

        assert is_model_allowed(StubCorrector(), "gpt-4o-mini")
        assert is_model_allowed(StubCorrector(), "qwen2.5:7b")


def test_model_backend_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCSIFTER_MODEL_BACKEND", "ollama")
    manager = ConfigManager(str(tmp_path / "config.json"))

    assert manager.config["model_backend"] == "ollama"
    assert "model_backend" in manager.environment_override_keys
