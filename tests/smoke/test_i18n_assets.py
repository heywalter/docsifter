import json
import re
from html.parser import HTMLParser
from pathlib import Path

import docsifter

PACKAGE_DIR = Path(docsifter.__file__).resolve().parent


def _quoted_js_keys(source):
    return {
        json.loads(match.group(1))
        for match in re.finditer(r'^\s*("(?:\\.|[^"])+")\s*:', source, re.MULTILINE)
    }


def _english_catalog(source):
    entries = re.finditer(
        r'^\s*("(?:\\.|[^"])+")\s*:\s*("(?:\\.|[^"])*")\s*,?\s*$',
        source.split("\n\n(function", 1)[0],
        re.MULTILINE,
    )
    return {json.loads(match.group(1)): json.loads(match.group(2)) for match in entries}


class _VisibleChineseTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocked_depth = 0
        self.values = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "textarea", "code", "pre"}:
            self.blocked_depth += 1
        for name, value in attrs:
            if name in {"placeholder", "title", "aria-label"} and value:
                self.values.append(value.strip())

    def handle_endtag(self, tag):
        if tag in {"script", "style", "textarea", "code", "pre"}:
            self.blocked_depth = max(0, self.blocked_depth - 1)

    def handle_data(self, data):
        if not self.blocked_depth and data.strip():
            self.values.append(data.strip())


def test_i18n_assets_are_wired_before_app_script():
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'id="langToggleBtn"' in html
    assert '<script src="/static/js/security.js"></script>' in html
    assert '<script src="/static/js/i18n.js"></script>' in html
    assert html.index("/static/js/security.js") < html.index("/static/js/app.js")
    assert html.index("/static/js/i18n.js") < html.index("/static/js/app.js")
    assert "data-i18n-value" not in html


def test_app_i18n_keys_exist_in_english_catalog():
    app_js = (PACKAGE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")
    i18n_js = (PACKAGE_DIR / "static" / "js" / "i18n.js").read_text(encoding="utf-8")

    explicit_keys = {
        match.group(1) for match in re.finditer(r"(?:this|window\.I18n)\.t\(\s*'([^']+)'", app_js)
    }
    en_catalog = i18n_js.split("\n\n(function", 1)[0]
    catalog_keys = _quoted_js_keys(en_catalog)

    assert explicit_keys - catalog_keys == set()


def test_i18n_runtime_exposes_expected_api():
    i18n_js = (PACKAGE_DIR / "static" / "js" / "i18n.js").read_text(encoding="utf-8")

    for expected in [
        "window.I18n",
        "setLanguage",
        "translateText",
        "MutationObserver",
        "data-i18n-placeholder",
        "docsifter.language",
    ]:
        assert expected in i18n_js


def test_all_static_web_ui_text_has_an_english_translation():
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    i18n_js = (PACKAGE_DIR / "static" / "js" / "i18n.js").read_text(encoding="utf-8")
    catalog = _english_catalog(i18n_js)
    parser = _VisibleChineseTextParser()
    parser.feed(html)

    untranslated = []
    sorted_keys = sorted(catalog, key=len, reverse=True)
    for source in parser.values:
        if not re.search(r"[\u4e00-\u9fff]", source):
            continue
        translated = catalog.get(source, source)
        if translated == source:
            for key in sorted_keys:
                translated = translated.replace(key, catalog[key])
        if re.search(r"[\u4e00-\u9fff]", translated):
            untranslated.append(source)

    assert untranslated == []


def test_webhook_monitor_labels_are_localized():
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    i18n_js = (PACKAGE_DIR / "static" / "js" / "i18n.js").read_text(encoding="utf-8")

    for label in [
        "GitHub Webhook 监控",
        "Webhook 自动审阅",
        "通过 Webhook 实时接收 PR 变更事件",
        "保存监控配置",
    ]:
        assert label in html
        assert json.dumps(label, ensure_ascii=False) in i18n_js


def test_frontend_has_no_legacy_manual_github_task_polling():
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    app_js = (PACKAGE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert html.count('id="githubMonitorModal"') == 1
    assert 'id="monitorRepoUrl"' in html
    assert 'id="monitorWebhookUrl"' in html
    assert 'id="monitorWebhookSecret"' in html
    assert 'id="githubAutoDetectionConfig"' not in html
    assert "monitorGithubTask" not in app_js
    assert "/api/github/task-status" not in app_js


def test_frontend_polling_reads_the_latest_progress_history_entry():
    app_js = (PACKAGE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert "Array.isArray(result.data)" in app_js
    assert "result.data[result.data.length - 1]" in app_js


def test_web_ui_uses_event_listeners_instead_of_inline_handlers():
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    app_js = (PACKAGE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")

    assert not re.search(r"\son(?:click|change|input|keypress)=", html)
    assert not re.search(r"\son(?:click|change|input|keypress)=", app_js)


def test_web_ui_loads_no_assets_from_a_third_party():
    """The UI has to render on a closed network, and without telling a CDN.

    DocSifter's whole point is reviewing documentation locally; a stylesheet or
    webfont fetched from a CDN would leave an air-gapped user with an unstyled
    page and would show a third party who is running it.
    """
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")

    external = re.findall(r'(?:href|src)\s*=\s*"(https?://[^"]+)"', html)
    assert external == [], f"the Web UI must not load {external} from the network"


def test_vendored_assets_are_present_and_referenced():
    vendor_dir = PACKAGE_DIR / "static" / "vendor"
    html = (PACKAGE_DIR / "templates" / "index.html").read_text(encoding="utf-8")

    expected = {
        "tailwind.min.css",
        "fontawesome.min.css",
        "fa-solid-900.woff2",
        "fa-brands-400.woff2",
    }
    present = {path.name for path in vendor_dir.iterdir() if path.is_file()}
    assert expected <= present, f"missing vendored assets: {sorted(expected - present)}"

    for stylesheet in ("tailwind.min.css", "fontawesome.min.css"):
        assert f"vendor/{stylesheet}" in html

    # The font files are reached from the stylesheet, so its url() references
    # have to stay relative to the vendor directory.
    fontawesome = (vendor_dir / "fontawesome.min.css").read_text(encoding="utf-8")
    assert "../webfonts/" not in fontawesome
    assert "fa-solid-900.woff2" in fontawesome


def test_report_template_stays_self_contained():
    """A generated report is shared and archived; it must not need the network."""
    report_dir = PACKAGE_DIR / "templates" / "report"

    for path in sorted(report_dir.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        external = [
            url
            for url in re.findall(r"https?://[^\s\"')]+", text)
            if not url.startswith("http://www.w3.org/")  # SVG/XML namespaces
        ]
        assert external == [], f"{path.name} references {external}"
