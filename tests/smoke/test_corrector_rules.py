"""Unit tests for the core rule engine in docsifter.corrector."""

import json
import logging

import pytest

from docsifter.config import ConfigManager
from docsifter.corrector import FalsePositiveManager, TextCorrector


def make_corrector(**overrides) -> TextCorrector:
    """Build a rule-only corrector that never loads model dependencies."""
    config = {
        "whitelist": ["Kubernetes"],
        "forced_fixes": {},
        "rule_metadata": {},
        "skip_text_patterns": [],
        "skip_file_patterns": [],
    }
    config.update(overrides)
    return TextCorrector(config)


# --- skip and relevance checks -------------------------------------------------


def test_has_meaningful_text_rejects_short_or_symbolic():
    c = make_corrector()
    assert not c.has_meaningful_text("ab")
    assert not c.has_meaningful_text("。。。")
    assert not c.has_meaningful_text("12345")
    assert c.has_meaningful_text("这是一段说明文字")
    assert c.has_meaningful_text("plain words")


def test_should_skip_file_matches_pattern():
    c = make_corrector(skip_file_patterns=["vendor/", r"\.tmp$"])
    assert c.should_skip_file("docs/vendor/readme.md")
    assert c.should_skip_file("notes.tmp")
    assert not c.should_skip_file("docs/guide.adoc")


def test_should_skip_text_matches_pattern():
    c = make_corrector(skip_text_patterns=[r"do\s*not\s*review"])
    assert c.should_skip_text("Please DO NOT REVIEW this line")
    assert not c.should_skip_text("normal sentence")


# --- comment extraction --------------------------------------------------------


@pytest.mark.parametrize(
    "lang,prefix",
    [("python", "#"), ("java", "//"), ("sql", "--"), ("javascript", "//")],
)
def test_extract_line_comments_by_language(lang, prefix):
    c = make_corrector()
    comments = c.extract_line_comments(f"{prefix} 这是一段注释", lang=lang)
    assert comments == ["这是一段注释"]


def test_extract_line_comments_filters_noise():
    c = make_corrector()
    assert c.extract_line_comments("# 12345", lang="python") == []
    assert c.extract_line_comments("//ab", lang="javascript") == []
    assert c.extract_line_comments("", lang="python") == []


# --- asciidoc extraction -------------------------------------------------------


def test_asciidoc_extraction_skips_code_blocks():
    c = make_corrector()
    content = "前文说明\n----\nblock line should be ignored\n----\n后文说明\n"
    extracted = c._extract_text_from_asciidoc(content)
    texts = [t for _, _, t in extracted]
    assert any("前文说明" in t for t in texts)
    assert any("后文说明" in t for t in texts)
    assert not any("ignored" in t for t in texts)


def test_asciidoc_extraction_reports_original_line_numbers():
    c = make_corrector()
    content = "\n\n\n第三行的说明文字\n"
    extracted = c._extract_text_from_asciidoc(content)
    assert extracted[0][0] == 4


def test_asciidoc_extraction_strips_macros_links_and_markup():
    c = make_corrector()
    line = "参考 <<chapter-one>> 与 https://example.com 以及 *强调* 内容"
    extracted = c._extract_text_from_asciidoc(line)
    assert len(extracted) == 1
    clean = extracted[0][2]
    assert "<<chapter-one>>" not in clean
    assert "https://example.com" not in clean
    assert "*" not in clean
    assert "以及" in clean


# --- markdown extraction -------------------------------------------------------


def test_markdown_extraction_skips_fenced_code():
    c = make_corrector()
    content = "正文一行\n```python\ncode_line = 1\n```\n结尾一行\n"
    extracted = c._extract_text_from_markdown(content)
    texts = [t for _, _, t in extracted]
    assert len(texts) == 2
    assert not any("code_line" in t for t in texts)


def test_markdown_extraction_nested_fence_keeps_block_open():
    c = make_corrector()
    # A ``` fence inside a ~~~ block must not close the outer block.
    content = "~~~\n```python\nstill_code\n```\n~~~\n块外的说明\n"
    extracted = c._extract_text_from_markdown(content)
    texts = [t for _, _, t in extracted]
    assert texts == ["块外的说明"]


def test_markdown_extraction_strips_inline_markup():
    c = make_corrector()
    line = "## 标题与 **加粗** 以及 [链接](https://x.io) 和 ~~删除线~~"
    extracted = c._extract_text_from_markdown(line)
    assert len(extracted) == 1
    clean = extracted[0][2]
    assert "##" not in clean
    assert "**" not in clean
    assert "[链接](https://x.io)" not in clean
    assert "~~" not in clean
    assert "标题与" in clean


def test_markdown_extraction_keeps_underscores_inside_inline_code():
    c = make_corrector()
    line = "2. 在 `sync_config.yaml` 中设置 `retry_limit: 3`。"
    clean = c._extract_text_from_markdown(line)[0][2]
    # Emphasis stripping used to pair the two underscores across both spans and
    # silently report `syncconfig.yaml` / `retrylimit`, corrupting a real filename.
    assert "sync_config.yaml" in clean
    assert "retry_limit" in clean


def test_markdown_extraction_still_strips_emphasis_outside_code():
    c = make_corrector()
    clean = c._extract_text_from_markdown("普通的 *强调* 和 `a_b` 混合")[0][2]
    assert "*" not in clean
    assert "a_b" in clean


def test_asciidoc_extraction_keeps_inline_code_intact():
    c = make_corrector()
    clean = c._extract_text_from_asciidoc("执行 `git log --oneline` 查看提交历史。")[0][2]
    # The `--` comment stripper used to truncate the line at the flag.
    assert "git log --oneline" in clean
    assert "查看提交历史" in clean


def test_extract_text_from_file_dispatches_by_extension():
    c = make_corrector()
    md = c.extract_text_from_file("readme.md", "说明文字")
    adoc = c.extract_text_from_file("guide.adoc", "说明文字")
    other = c.extract_text_from_file("data.csv", "说明文字")
    assert len(md) == 1
    assert len(adoc) == 1
    assert other == []


# --- protection round-trips -----------------------------------------------------


def test_whitelist_roundtrip_preserves_protected_terms():
    c = make_corrector(whitelist=["Kubernetes"])
    protected, replacements = c.protect_whitelist_words("Kubernetes 集群部署")
    assert "__WHITELIST_0__" in protected
    restored = c.restore_whitelist_words(protected, replacements)
    assert restored == "Kubernetes 集群部署"


def test_syntax_protection_roundtrip_restores_all_regions():
    c = make_corrector()
    text = (
        "访问 https://example.com/docs 或 `run_cmd` 查看 [安装指南](install.md)，"
        "配置 {product-version} 属性，详见 <<chapter-two>>。"
    )
    protected, syntax = c.protect_asciidoc_syntax(text)
    assert protected != text
    assert "https://" not in protected
    restored = c.restore_protected_regions(protected, syntax)
    assert restored == text


def test_restore_safe_model_output_discards_tampered_regions(caplog):
    c = make_corrector()
    protected, syntax = c.protect_asciidoc_syntax("查看 https://example.com 页面")
    tampered = "查看 example-dot-com 页面"
    result = c.restore_safe_model_output(protected, tampered, syntax, {})
    assert result is None


def test_restore_safe_model_output_discards_unsafe_length():
    c = make_corrector()
    text, syntax = c.protect_asciidoc_syntax("这句话完全正常没有任何问题需要修改")
    result = c.restore_safe_model_output(text, "短", syntax, {})
    assert result is None


# --- technical-density guard -----------------------------------------------------


def test_should_protect_text_flags_technical_density():
    c = make_corrector()
    dense = "Contact HTTP API v1.2 at ops@example.com or visit https://x.io now"
    assert c.should_protect_text(dense)
    assert not c.should_protect_text("这句是普通的中文说明，没有技术标记")


def test_is_balanced_brackets():
    c = make_corrector()
    assert c.is_balanced_brackets("普通（中文）与 [英文] 都配对")
    assert not c.is_balanced_brackets("缺少闭合（括号")
    assert not c.is_balanced_brackets("先闭后开 )(")


def test_filter_model_artifacts_strips_reasoning_tags():
    c = make_corrector()
    raw = "<think>internal reasoning</think>修正后的句子"
    assert c._filter_model_artifacts(raw) == "修正后的句子"


# --- forced fixes and metadata ---------------------------------------------------


def test_apply_forced_fixes_with_metadata_reports_highest_severity():
    c = make_corrector(
        forced_fixes={r"文挡": "文档", "请客官": "请您"},
        rule_metadata={
            r"文挡": {"id": "typo.wendang", "severity": "warning"},
            "请客官": {"id": "style.address", "severity": "suggestion"},
        },
    )
    fixed, matches = c.apply_forced_fixes_with_metadata("这是一个文挡示例")
    assert fixed == "这是一个文档示例"
    ids = {m["id"] for m in matches}
    assert ids == {"typo.wendang"}
    assert all(m["severity"] == "warning" for m in matches)


def test_correct_text_with_metadata_rule_only_path():
    c = make_corrector(
        forced_fixes={r"文挡": "文档"},
        rule_metadata={r"文挡": {"id": "typo.wendang", "severity": "error"}},
    )
    corrected, meta = c.correct_text_with_metadata("检查这份文挡")
    assert corrected == "检查这份文档"
    assert meta["review_source"] == "rule"
    assert meta["severity"] == "error"
    assert meta["rule_ids"] == ["typo.wendang"]


def test_correct_text_with_metadata_no_change_returns_none():
    c = make_corrector()
    corrected, meta = c.correct_text_with_metadata("无需修改的规范表述")
    assert corrected is None
    assert meta["review_source"] == "none"


def test_forced_fix_does_not_corrupt_whitelisted_terms():
    c = make_corrector(forced_fixes={r"挡": "档"})
    corrected, _ = c.correct_text_with_metadata("Kubernetes 文挡校验")
    assert corrected is not None
    assert "Kubernetes" in corrected
    assert "文档" in corrected


# --- end-to-end file processing ---------------------------------------------------


def test_process_file_end_to_end_markdown():
    c = make_corrector(
        forced_fixes={r"文挡": "文档"},
        rule_metadata={r"文挡": {"id": "typo.wendang", "severity": "warning"}},
    )
    changes = c.process_file("doc.md", "# 使用指南\n\n请阅读这份文挡。\n")
    assert len(changes) == 1
    change = changes[0]
    assert change["line_number"] == 3
    assert change["original_text"] == "请阅读这份文挡。"
    assert change["corrected_text"] == "请阅读这份文档。"
    assert change["source"] == "text"
    assert change["review_source"] == "rule"
    assert change["rule_ids"] == ["typo.wendang"]


def test_process_file_respects_file_skip_patterns():
    c = make_corrector(skip_file_patterns=["generated"])
    assert c.process_file("generated/doc.md", "任何内容") == []


# --- false positive manager --------------------------------------------------------


@pytest.fixture()
def fp_manager(tmp_path):
    fp_file = tmp_path / "false_positives.json"
    fp_file.write_text("[]", encoding="utf-8")
    return FalsePositiveManager(str(fp_file))


def test_false_positive_exact_match(fp_manager):
    fp_manager.add_false_positive("原始建议", "修改建议")
    assert fp_manager.is_false_positive("原始建议", "修改建议")
    assert not fp_manager.is_false_positive("原始建议", "其他建议")
    assert not fp_manager.is_false_positive("其他原文", "修改建议")


def test_false_positive_pattern_requires_full_match(fp_manager):
    fp_manager.add_false_positive(r"第.+条", "", is_pattern=True)
    assert fp_manager.is_false_positive("第三条", "")
    assert not fp_manager.is_false_positive("见第三条内容", "")


def test_false_positive_skips_sentence_like_patterns(fp_manager):
    long_sentence = "这" * 120
    fp_manager.add_false_positive(long_sentence, "", is_pattern=True)
    assert not fp_manager.is_false_positive(long_sentence, "")
    with_punct = "包含|竖线的模式"
    fp_manager.add_false_positive(with_punct, "", is_pattern=True)
    assert not fp_manager.is_false_positive("包含|竖线的模式", "")


def test_false_positive_manager_migrates_legacy_dict_format(tmp_path):
    fp_file = tmp_path / "legacy.json"
    legacy = {
        "exact_matches": [{"original": "甲", "corrected": "乙"}],
        "patterns": ["模式A"],
    }
    fp_file.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    manager = FalsePositiveManager(str(fp_file))
    assert len(manager.false_positives) == 2
    exact = next(fp for fp in manager.false_positives if not fp["is_pattern"])
    pattern = next(fp for fp in manager.false_positives if fp["is_pattern"])
    assert exact == {"original": "甲", "corrected": "乙", "is_pattern": False}
    assert pattern == {"original": "模式A", "corrected": "", "is_pattern": True}


def test_false_positive_save_and_reload_roundtrip(fp_manager):
    fp_manager.add_false_positive("原文X", "修正Y", note="人工确认")
    reloaded = FalsePositiveManager(fp_manager.false_positive_file)
    assert reloaded.is_false_positive("原文X", "修正Y")


def test_forced_fixes_cannot_corrupt_a_protected_region(caplog):
    # A rule normalizing underscores matches inside "__CODE_0__". Restoring the
    # damaged placeholder used to fall back to its bare index, replacing every
    # "0" in the sentence, so "30 秒" became "3`retry_limit` 秒".
    c = make_corrector(forced_fixes={"_+": ""})
    text = "超时设置为 30 秒，参见 `retry_limit` 配置。"

    with caplog.at_level(logging.WARNING):
        corrected, meta = c.correct_text_with_metadata(text)

    assert corrected is None
    assert meta["rule_ids"] == []
    assert "damaged a protected region" in caplog.text


def test_restore_protected_regions_never_guesses_at_a_missing_placeholder():
    c = make_corrector()
    _, syntax = c.protect_asciidoc_syntax("参见 `retry_limit` 配置")

    # The placeholder is gone; a bare index must not be treated as one.
    damaged = "超时 30 秒 CODE0"
    assert c.restore_protected_regions(damaged, syntax) == damaged


def test_placeholders_intact_detects_damage():
    c = make_corrector()
    protected, syntax = c.protect_asciidoc_syntax("参见 `retry_limit` 配置")

    assert c.placeholders_intact(protected, protected, syntax) is True
    assert c.placeholders_intact(protected, protected.replace("_", ""), syntax) is False


def test_intact_forced_fixes_still_apply_alongside_protection():
    c = make_corrector(forced_fixes={"轮循": "轮询"})
    corrected, meta = c.correct_text_with_metadata("轮循策略见 `retry_limit` 配置")

    assert corrected == "轮询策略见 `retry_limit` 配置"
    assert meta["review_source"] == "rule"


def test_chinese_prose_naming_a_technology_still_reaches_the_model():
    c = make_corrector()
    # Chinese has no spaces, so the word count of a whole sentence is tiny and a
    # single acronym used to clear the density threshold, skipping the model for
    # a fifth of this project's own documentation.
    assert c.should_protect_text("这份文档介召了 API 网关的整体架构") is False
    assert c.should_protect_text("生成包含统计、差异和缺陷率的 HTML 报告。") is False


def test_machine_readable_lines_are_still_held_back():
    c = make_corrector()
    for text in (
        "访问 https://docs.example.com/guide 获取完整教程",
        "镜像 registry.example.com/docsifter-ai:0.3 已推送到内网仓库",
        "服务默认监听 0.0.0.0:8765 端口可用环境变量覆盖",
    ):
        assert c.should_protect_text(text) is True, text


def _default_rule_corrector() -> TextCorrector:
    """Corrector carrying the shipped rule set, not an empty one."""
    defaults = ConfigManager.get_default_config(ConfigManager.__new__(ConfigManager))
    return make_corrector(
        forced_fixes=defaults["forced_fixes"], rule_metadata=defaults["rule_metadata"]
    )


def test_login_rule_reaches_past_a_product_name():
    c = _default_rule_corrector()
    # "登陆到 Grafana 控制台" is the ordinary shape in Chinese technical writing;
    # requiring the context noun to follow 到 directly missed it silently.
    for text, expected in (
        ("使用管理员帐号登陆到 Grafana 控制台", "使用管理员账号登录到 Grafana 控制台"),
        ("登陆到 Jenkins 后台查看构建", "登录到 Jenkins 后台查看构建"),
        ("登陆至 AWS 控制台", "登录至 AWS 控制台"),
    ):
        assert c.correct_text(text) == expected, text


def test_login_rule_leaves_the_landing_sense_alone():
    c = _default_rule_corrector()
    for text in ("飞机登陆跑道", "台风即将登陆华南沿海", "登陆月球是人类的壮举", "诺曼底登陆战役"):
        assert c.correct_text(text) is None, text


def test_a_run_of_particles_collapses_to_one():
    c = _default_rule_corrector()
    # As the literal string "的的" this replaced pairs left to right, so a run of
    # three came out as two and the corpus had recorded that as expected.
    assert c.correct_text("这是明确的的的重复用字") == "这是明确的重复用字"
    assert c.correct_text("这是明确的的重复用字") == "这是明确的重复用字"
    assert c.correct_text("正常的文字不受影响") is None
