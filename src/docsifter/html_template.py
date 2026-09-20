#!/usr/bin/env python3
"""HTML report template loader.

The report markup, styles, and scripts live in ``docsifter/templates/report/``
so they can be edited as plain web assets instead of Python string literals.
Dynamic values are injected through single-pass ``{{TOKEN}}`` substitution; no
external templating engine is involved and the output stays self-contained.
"""

import datetime
import html
import re
from functools import cache
from importlib import resources

_TEMPLATE_DIR = "templates/report"
_TOKEN_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


@cache
def _load_template(name: str) -> str:
    return resources.files("docsifter").joinpath(_TEMPLATE_DIR, name).read_text(encoding="utf-8")


def _render(name: str, values: dict) -> str:
    """Replace ``{{TOKENS}}`` in one pass so inserted values are never rescanned."""

    def substitute(match: re.Match) -> str:
        return str(values.get(match.group(1), match.group(0)))

    return _TOKEN_RE.sub(substitute, _load_template(name))


class HTMLTemplate:
    def get_css_styles(self):
        return _load_template("styles.css")

    def get_javascript(self):
        return _load_template("scripts.js")

    def generate_hero_section(self, model_info="1.5B parameters"):
        return _render(
            "hero.html",
            {
                "GENERATED_AT": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "MODEL_INFO": html.escape(str(model_info)),
            },
        )

    def generate_stats_section(self, stats_data):
        valid_changes = stats_data["valid_changes"]
        total_changes = stats_data["total_changes"]
        total_files = stats_data["total_files"]
        total_chars = stats_data["total_chars"]
        defect_rate = stats_data["defect_rate_per_thousand"]
        avg_per_file = valid_changes / max(1, total_files)
        return _render(
            "stats.html",
            {
                "TOTAL_FILES": total_files,
                "VALID_CHANGES": valid_changes,
                "TOTAL_CHANGES": total_changes,
                "WHITESPACE_CHANGES": stats_data["total_whitespace_changes"],
                "VALID_RATIO_PCT": f"{min(100, (valid_changes / max(1, total_changes)) * 100):.1f}",
                "TOTAL_CHARS": f"{total_chars:,}",
                "CHARS_PCT": f"{min(100, (total_chars / max(1, 50000)) * 100):.1f}",
                "AVG_PER_FILE": f"{avg_per_file:.1f}",
                "AVG_PCT": f"{min(100, avg_per_file * 20):.1f}",
                "DEFECT_RATE": f"{defect_rate:.1f}",
                "DEFECT_PCT": f"{min(100, defect_rate * 10):.1f}",
            },
        )

    def generate_modal(self):
        return _load_template("modal.html")

    def generate_full_html(self, stats_data, files_content, model_info="1.5B parameters"):
        return _render(
            "page.html",
            {
                "STYLES": self.get_css_styles(),
                "HERO": self.generate_hero_section(model_info),
                "STATS": self.generate_stats_section(stats_data),
                "FILES_CONTENT": files_content,
                "MODAL": self.generate_modal(),
                "SCRIPTS": self.get_javascript(),
            },
        )
