"""Tests for the optional LLM cross-line (context) review pass."""

from docsifter import orchestrator as orchestrator_module
from docsifter.llm_reviewer import (
    CONTEXT_MAX_LINES,
    CONTEXT_SYSTEM_PROMPT,
    LLMReviewer,
    LLMReviewError,
)


class FakeContextReviewer:
    def __init__(self, issues=None, error=None):
        self.issues = issues or []
        self.error = error
        self.calls = []

    def review_context(self, lines):
        self.calls.append(lines)
        if self.error:
            raise self.error
        return self.issues


def make_issue(**overrides):
    issue = {
        "refs": [3],
        "context_type": "inconsistency",
        "issue": "术语不一致",
        "suggestion": "统一为同一术语",
    }
    issue.update(overrides)
    return issue


def make_reviewer(monkeypatch, tmp_path, fake):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    from docsifter.orchestrator import DocumentReviewer

    monkeypatch.setattr(orchestrator_module, "load_context_reviewer", lambda cm: fake)
    return DocumentReviewer(server_mode=True)


def test_context_findings_appended_and_counted(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# 部署指南\n\n请登陆帐户。\n\n数据保存在主节点上。\n", encoding="utf-8"
    )
    fake = FakeContextReviewer(issues=[make_issue(refs=[2, 4])])
    reviewer = make_reviewer(monkeypatch, tmp_path, fake)

    result = reviewer.process_directory(str(docs))

    entry = next(r for r in result["results"] if r["file_path"].endswith("guide.md"))
    context_changes = [c for c in entry["changes"] if c.get("review_source") == "context"]
    assert len(context_changes) == 1
    change = context_changes[0]
    assert change["rule_ids"] == ["context"]
    assert change["context_refs"] == [2, 4]
    assert change["line_number"] == 2
    assert change["is_whitespace"] is False
    assert result["stats"]["valid_changes"] >= 1
    # The fake received (line_number, plain_text) pairs.
    assert fake.calls and all(isinstance(no, int) for no, _ in fake.calls[0])


def test_clean_files_are_skipped_under_the_default_scope(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "clean.md").write_text("这是一段完全正常的描述文字。", encoding="utf-8")
    fake = FakeContextReviewer(issues=[make_issue()])
    reviewer = make_reviewer(monkeypatch, tmp_path, fake)

    result = reviewer.process_directory(str(docs))

    # A whole document goes out per request, so by default this layer follows
    # findings like the rest of the pipeline instead of the document count.
    assert reviewer.config["context_review_scope"] == "flagged"
    assert fake.calls == []
    assert not any(r["file_path"].endswith("clean.md") for r in result["results"])


def test_clean_files_are_reviewed_when_the_scope_is_all(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "clean.md").write_text("这是一段完全正常的描述文字。", encoding="utf-8")
    fake = FakeContextReviewer(issues=[make_issue()])
    reviewer = make_reviewer(monkeypatch, tmp_path, fake)
    reviewer.config["context_review_scope"] = "all"

    result = reviewer.process_directory(str(docs))

    # A clean file can still contradict itself; that is what this scope buys.
    assert len(fake.calls) == 1
    entry = next(r for r in result["results"] if r["file_path"].endswith("clean.md"))
    assert any(c.get("review_source") == "context" for c in entry["changes"])


def test_context_reviewer_error_does_not_break_the_run(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("请登陆帐户。", encoding="utf-8")
    fake = FakeContextReviewer(error=LLMReviewError("endpoint down"))
    reviewer = make_reviewer(monkeypatch, tmp_path, fake)

    result = reviewer.process_directory(str(docs))

    assert result["stats"]["total_files"] == 1
    assert not any(
        c.get("review_source") == "context" for r in result["results"] for c in r["changes"]
    )


def test_context_review_disabled_by_default(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("请登陆帐户。", encoding="utf-8")
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    from docsifter.orchestrator import DocumentReviewer

    reviewer = DocumentReviewer(server_mode=True)
    result = reviewer.process_directory(str(docs))

    assert not any(
        c.get("review_source") == "context" for r in result["results"] for c in r["changes"]
    )


def make_llm_reviewer() -> LLMReviewer:
    return LLMReviewer({"endpoint": "http://llm.example", "model": "test-model"})


def test_parse_context_issues_tolerates_prose_and_bad_entries():
    reviewer = make_llm_reviewer()
    content = (
        "Here are the issues:\n"
        '[{"lines": [2, 3], "type": "contradiction", "issue": "前后矛盾", '
        '"suggestion": "统一表述"},\n'
        '{"not_relevant": true},\n'
        '{"lines": [], "issue": "缺少行号应被丢弃"}]\n'
        "Hope this helps!"
    )
    issues = reviewer._parse_context_issues(content)
    assert len(issues) == 1
    assert issues[0]["refs"] == [2, 3]
    assert issues[0]["context_type"] == "contradiction"


def test_parse_context_issues_caps_result_count():
    reviewer = make_llm_reviewer()
    entries = ",".join(
        f'{{"lines": [{n}], "type": "style", "issue": "问题{n}", "suggestion": ""}}'
        for n in range(1, 16)
    )
    issues = reviewer._parse_context_issues(f"[{entries}]")
    assert len(issues) == 10


def test_review_context_sends_numbered_lines_with_system_prompt():
    reviewer = make_llm_reviewer()
    captured = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return "[]"

    reviewer._chat = fake_chat
    lines = [(no, f"第{no}行内容") for no in range(1, CONTEXT_MAX_LINES + 50)]

    assert reviewer.review_context(lines) == []
    system, user = captured["messages"]
    assert system["role"] == "system"
    assert system["content"] == CONTEXT_SYSTEM_PROMPT
    body_lines = user["content"].split("\n")
    assert len(body_lines) == CONTEXT_MAX_LINES
    assert body_lines[0].startswith("1: 第1行内容")


def test_context_review_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCSIFTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DOCSIFTER_CONTEXT_REVIEW_ENABLED", "1")
    from docsifter.config import ConfigManager

    manager = ConfigManager()
    assert manager.config["context_review_enabled"] is True
    assert "context_review_enabled" in manager.environment_override_keys
