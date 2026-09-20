import json
import os
from pathlib import Path

import pytest

import docsifter
from docsifter.config import ConfigManager
from docsifter.corrector import ModelExecutionError, ModelUnavailableError, TextCorrector
from docsifter.file_processor import FileProcessor
from docsifter.html_generator import HTMLGenerator

PACKAGE_DIR = Path(docsifter.__file__).resolve().parent
RECOMMENDED_MODEL = "shibing624/chinese-text-correction-1.5b"


def test_environment_overrides(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"email_notifications_enabled": False}), encoding="utf-8")

    monkeypatch.setenv("DOCSIFTER_EMAIL_PASSWORD", "local-secret")
    monkeypatch.setenv("DOCSIFTER_EMAIL_RECIPIENTS", "one@example.com,two@example.com")
    monkeypatch.setenv("DOCSIFTER_EMAIL_NOTIFICATIONS_ENABLED", "true")

    config = ConfigManager(str(config_path)).get_config()

    assert config["email_password"] == "local-secret"
    assert config["email_recipients"] == ["one@example.com", "two@example.com"]
    assert config["email_notifications_enabled"] is True


def test_skip_text_patterns_are_applied_and_legacy_key_is_migrated(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"blacklist_patterns": [r"^SKIP"]}),
        encoding="utf-8",
    )

    config = ConfigManager(str(config_path)).get_config()
    corrector = TextCorrector(config, server_mode=True)

    assert "blacklist_patterns" not in config
    assert config["skip_text_patterns"] == [r"^SKIP"]
    assert corrector.correct_text("SKIP 请登陆帐户") is None
    assert corrector.correct_text("请登陆帐户") == "请登录账户"


def test_recommended_model_is_cpu_friendly_1_5b(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)

    assert config["default_model"] == RECOMMENDED_MODEL
    assert corrector.current_model == RECOMMENDED_MODEL


def test_config_enabled_ai_initializes_the_declared_default_model(monkeypatch, tmp_path):
    import docsifter.corrector as corrector_module

    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    config["ai_correction_enabled"] = True

    class ValidModel:
        def __init__(self, model_name_or_path=None):
            self.model_name_or_path = model_name_or_path

        def correct_batch(self, _texts):
            return [{"target": "测试文档", "errors": []}]

    monkeypatch.setattr(corrector_module, "load_gpt_corrector", lambda: True)
    monkeypatch.setattr(corrector_module, "GptCorrector", ValidModel)

    corrector = TextCorrector(config)

    assert corrector.gpt_client.model_name_or_path == RECOMMENDED_MODEL


def test_web_model_choices_are_limited_to_the_supported_runtime():
    from docsifter.orchestrator import WEB_ALLOWED_MODELS

    assert WEB_ALLOWED_MODELS == {
        "rule-based",
        RECOMMENDED_MODEL,
        "shibing624/chinese-text-correction-7b",
    }
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    assert "twnlp/" not in html


def test_codex_review_contract_is_documented():
    readme = Path("README.md").read_text(encoding="utf-8")
    readme_cn = Path("README-CN.md").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")

    assert "Layered AI Review" in readme
    assert "does not require Codex to run" in readme
    assert "分层 AI 审阅" in readme_cn
    assert "本身不依赖 Codex 运行" in readme_cn
    assert "Codex context review" in agents
    assert RECOMMENDED_MODEL in agents


def test_sample_docs_are_scannable():
    sample_dir = Path("examples/sample-docs")
    files = FileProcessor().get_all_supported_files(str(sample_dir))

    assert str(sample_dir / "quick-start.adoc") in files
    assert str(sample_dir / "release-notes.md") in files


def test_directory_scan_excludes_generated_and_dependency_trees_by_default(tmp_path):
    included = tmp_path / "docs" / "guide.md"
    included.parent.mkdir()
    included.write_text("Guide", encoding="utf-8")

    excluded_files = []
    for directory in [".git", ".venv", "node_modules", "dist", ".pytest_cache"]:
        path = tmp_path / directory / "ignored.md"
        path.parent.mkdir()
        path.write_text("Ignore", encoding="utf-8")
        excluded_files.append(str(path))

    files = FileProcessor().get_all_supported_files(str(tmp_path))

    assert str(included) in files
    assert set(excluded_files).isdisjoint(files)
    assert str(tmp_path / ".venv" / "ignored.md") in FileProcessor(
        excluded_directories=[]
    ).get_all_supported_files(str(tmp_path / ".venv"))


def test_sample_docs_include_rule_based_demo_corrections(tmp_path):
    sample_dir = Path("examples/sample-docs")
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)

    changes = []
    for file_path in FileProcessor().get_all_supported_files(str(sample_dir)):
        content = Path(file_path).read_text(encoding="utf-8")
        changes.extend(corrector.process_file(file_path, content))

    corrections = {(item["original_text"], item["corrected_text"]) for item in changes}
    sample_text = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("examples/sample-docs").iterdir()
    )

    assert "上诉事件" not in sample_text
    assert any(
        "登陆帐户" in original and "登录账户" in corrected for original, corrected in corrections
    )
    assert (
        "为新用户创建帐号，并确认用户可以访问工作区。",
        "为新用户创建账号，并确认用户可以访问工作区。",
    ) in corrections
    assert ("修复了登陆流程中的的提示文案。", "修复了登录流程中的提示文案。") in corrections


def test_rules_preserve_inline_code_in_markdown_and_asciidoc(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)

    assert corrector.process_file("demo.md", "请运行 `登陆` 命令。") == []
    assert corrector.process_file("demo.adoc", "请运行 `登陆` 命令。") == []
    assert (
        corrector.correct_text("请访问 [登陆](https://example.com/登陆) 并运行 **`登陆`**。")
        is None
    )


def test_markdown_review_skips_backtick_and_tilde_fences(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)
    content = """Outside 登陆帐户
~~~text
Inside 登陆帐户
~~~
````markdown
Also inside 登陆帐户
````
"""

    changes = corrector.process_file("demo.md", content)

    assert [change["line_number"] for change in changes] == [1]
    assert changes[0]["corrected_text"] == "Outside 登录账户"


def test_asciidoc_review_resumes_after_markdown_style_fence(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)
    content = """Before 登陆帐户
```text
Inside 登陆帐户
```
After 登陆帐户
"""

    changes = corrector.process_file("demo.adoc", content)

    assert [change["line_number"] for change in changes] == [1, 5]


def test_rule_correction_continues_into_model_review(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)
    received = []

    class FakeModel:
        def correct_batch(self, texts):
            received.extend(texts)
            return [{"target": texts[0] + "，并完成检查。", "errors": []}]

    corrector.ai_correction_enabled = True
    corrector.gpt_client = FakeModel()
    corrected, metadata = corrector.correct_text_with_metadata("请登陆帐户")

    assert received == ["请登录账户"]
    assert corrected == "请登录账户，并完成检查。"
    assert metadata["review_source"] == "rule+model"
    assert metadata["rule_ids"] == [
        "zh.terminology.login",
        "zh.terminology.user-account",
    ]


def test_model_output_cannot_drop_protected_content(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)

    class DestructiveModel:
        def correct_batch(self, _texts):
            return [{"target": "请登录账户", "errors": []}]

    corrector.ai_correction_enabled = True
    corrector.gpt_client = DestructiveModel()

    corrected, metadata = corrector.correct_text_with_metadata("运行 `登陆` 后请登陆帐户")

    assert corrected == "运行 `登陆` 后请登录账户"
    assert metadata["review_source"] == "rule"
    assert metadata["rule_ids"] == [
        "zh.terminology.login",
        "zh.terminology.user-account",
    ]


def test_rule_and_model_review_preserves_error_severity(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)

    class FakeModel:
        def correct_batch(self, texts):
            return [{"target": texts[0] + "。", "errors": []}]

    corrector.ai_correction_enabled = True
    corrector.gpt_client = FakeModel()
    corrected, metadata = corrector.correct_text_with_metadata("这里的的内容")

    assert corrected == "这里的内容。"
    assert metadata == {
        "review_source": "rule+model",
        "severity": "error",
        "rule_ids": ["zh.repetition.de"],
    }


def test_model_validation_and_empty_inference_are_not_silent(monkeypatch, tmp_path):
    import docsifter.corrector as corrector_module

    config = ConfigManager(str(tmp_path / "config.json")).get_config()

    class InvalidModel:
        def __init__(self, model_name_or_path=None):
            self.model_name_or_path = model_name_or_path

        def correct_batch(self, texts):
            return [{"target": texts[0], "errors": []}]

    monkeypatch.setattr(corrector_module, "load_gpt_corrector", lambda: True)
    monkeypatch.setattr(corrector_module, "GptCorrector", InvalidModel)
    invalid_corrector = TextCorrector(config, server_mode=True)

    with pytest.raises(ModelUnavailableError, match="validation"):
        invalid_corrector.update_model(RECOMMENDED_MODEL)

    class EmptyModel:
        def correct_batch(self, texts):
            return []

    empty_corrector = TextCorrector(config, server_mode=True)
    empty_corrector.ai_correction_enabled = True
    empty_corrector.gpt_client = EmptyModel()

    with pytest.raises(ModelExecutionError, match="empty correction result"):
        empty_corrector.correct_text("这是一段正常文本。")


def test_default_rules_exclude_context_dependent_replacements(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()

    for risky_pattern in ["上诉", "压盖", "有着", "做过滤", "某图"]:
        assert risky_pattern not in config["forced_fixes"]

    assert set(config["rule_metadata"]) == set(config["forced_fixes"])
    assert all(
        {"id", "message", "severity"} <= set(rule) for rule in config["rule_metadata"].values()
    )
    assert config["skip_file_patterns"] == []
    assert all(
        "格式" not in pattern and "语法" not in pattern for pattern in config["skip_text_patterns"]
    )


def test_login_rule_keeps_literal_landing_contexts(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json")).get_config()
    corrector = TextCorrector(config, server_mode=True)

    assert corrector.correct_text("探测器将在月球表面登陆。") is None
    assert corrector.correct_text("请登陆帐户。") == "请登录账户。"
    assert corrector.correct_text("修复登陆流程中的提示。") == "修复登录流程中的提示。"


def test_html_report_shows_finding_provenance(tmp_path):
    report_path = tmp_path / "report.html"
    HTMLGenerator(str(tmp_path)).generate_report(
        [
            {
                "file": str(tmp_path / "demo.md"),
                "line_map": {0: 1},
                "lines": [
                    {
                        "original": "请登陆",
                        "corrected": "请登录",
                        "review_source": "rule",
                        "severity": "warning",
                        "rule_ids": ["zh.terminology.login"],
                    }
                ],
            }
        ],
        str(report_path),
    )

    report = report_path.read_text(encoding="utf-8")
    assert ">rule</span>" in report
    assert ">warning</span>" in report
    assert "zh.terminology.login" in report


# --- resource guards ------------------------------------------------------------


def test_symlinked_document_is_not_reviewed(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    outside = tmp_path / "outside-the-tree.txt"
    outside.write_text("内容在被审阅的目录之外", encoding="utf-8")
    os.symlink(outside, docs / "innocent.txt")

    processor = FileProcessor()

    # Following it both reads outside the reviewed tree and, when it points at a
    # character device, never returns while holding the shared review lock.
    assert processor.get_all_supported_files(str(docs)) == []
    assert processor.read_file_content(str(docs / "innocent.txt")) == ""


def test_oversized_document_is_skipped(tmp_path):
    small = tmp_path / "small.md"
    small.write_text("正常大小的文档内容", encoding="utf-8")
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * (2 * 1024 * 1024))

    processor = FileProcessor(max_file_size_mb=1)

    assert processor.get_all_supported_files(str(tmp_path)) == [str(small)]
    assert processor.read_file_content(str(big)) == ""
    assert processor.read_file_content(str(small)) == "正常大小的文档内容"


def test_size_guard_also_covers_the_github_changed_file_path(tmp_path):
    # The GitHub path builds its list from the pull request's changed files and
    # never calls get_all_supported_files, so the guard has to hold in the read.
    big = tmp_path / "changed.md"
    big.write_bytes(b"x" * (2 * 1024 * 1024))

    assert FileProcessor(max_file_size_mb=1).read_file_content(str(big)) == ""


def test_missing_file_is_reported_not_raised(tmp_path):
    processor = FileProcessor()
    assert processor.is_reviewable_file(str(tmp_path / "nope.md")) is False
    assert processor.read_file_content(str(tmp_path / "nope.md")) == ""


def test_the_model_extra_and_requirements_file_stay_in_step():
    """Two files name the model runtime, and they must not drift.

    pyproject's `model` extra is what a PyPI install resolves; the Dockerfile
    installs requirements-model.txt before the source is copied in, so it cannot
    reference the project and has to keep its own copy of the pins.
    """
    import re
    from pathlib import Path

    # tomllib arrived in 3.11 and this project supports 3.10; the check still
    # runs on every other leg of the matrix, which is enough to catch drift.
    tomllib = pytest.importorskip("tomllib")

    root = Path(__file__).resolve().parents[2]

    with (root / "pyproject.toml").open("rb") as handle:
        extra = tomllib.load(handle)["project"]["optional-dependencies"]["model"]

    requirements = [
        line.strip()
        for line in (root / "requirements-model.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert sorted(extra) == sorted(requirements), (
        "pyproject's model extra and requirements-model.txt disagree; "
        "update both or a PyPI install and a Docker build get different pins"
    )
    for pin in extra:
        assert re.match(r"^[A-Za-z0-9._-]+[><=!~]", pin), f"unpinned model dependency: {pin}"
