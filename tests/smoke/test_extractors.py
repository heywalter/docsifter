"""Tests for the pluggable text-extraction registry (docsifter.extractors)."""

import pytest

from docsifter import extractors
from docsifter.corrector import TextCorrector


def make_corrector() -> TextCorrector:
    config = {
        "whitelist": ["Kubernetes"],
        "forced_fixes": {},
        "rule_metadata": {},
        "skip_text_patterns": [],
        "skip_file_patterns": [],
    }
    return TextCorrector(config)


@pytest.fixture(autouse=True)
def restore_registry():
    """Keep custom registrations from leaking between tests."""
    snapshot = dict(extractors.TEXT_EXTRACTORS)
    yield
    extractors.TEXT_EXTRACTORS.clear()
    extractors.TEXT_EXTRACTORS.update(snapshot)


def test_builtin_formats_are_registered():
    extensions = set(extractors.supported_extensions())
    assert {".adoc", ".asciidoc", ".asc", ".txt"} <= extensions
    assert {".md", ".markdown"} <= extensions


def test_unsupported_extension_returns_empty():
    c = make_corrector()
    assert c.extract_text_from_file("notes.xyz", "随便什么内容") == []


def test_extension_lookup_is_case_insensitive():
    c = make_corrector()
    extracted = c.extract_text_from_file("README.MD", "# 这是一个标题\n\n正文内容。")
    assert extracted
    assert all(isinstance(item[0], int) for item in extracted)


def test_custom_format_registers_without_engine_changes():
    def extract_rst(content):
        return [
            (i + 1, line, line.strip())
            for i, line in enumerate(content.split("\n"))
            if line.strip()
        ]

    register = extractors.register_text_extractor
    register([".rst"], extract_rst)
    c = make_corrector()
    extracted = c.extract_text_from_file("guide.rst", "第一节内容\n第二节内容")
    assert [item[2] for item in extracted] == ["第一节内容", "第二节内容"]
    assert [item[0] for item in extracted] == [1, 2]


def test_override_builtin_extension_is_deliberate_and_effective():
    def extract_upper(content):
        return [(1, content, content.upper())]

    extractors.register_text_extractor([".md"], extract_upper)
    c = make_corrector()
    assert c.extract_text_from_file("x.md", "hello")[0][2] == "HELLO"


def test_module_extractors_match_method_output():
    c = make_corrector()
    content = "# 标题\n\n这一句有的的的重复。\n\n```python\n# 代码注释\n```\n"
    assert c._extract_text_from_markdown(content) == extractors.extract_markdown_text(content)
    adoc = "= 示例\n\n登陆帐户后查看 ---- 代码块 ----\n"
    assert c._extract_text_from_asciidoc(adoc) == extractors.extract_asciidoc_text(adoc)
