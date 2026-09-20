#!/usr/bin/env python3
"""HTML report generation from review results."""

import difflib
import hashlib
import html
import logging
import os
import re

from .html_template import HTMLTemplate

logger = logging.getLogger(__name__)


class HTMLGenerator:
    def __init__(self, base_dir=""):
        self.base_dir = base_dir

    def format_path_for_display(self, file_path):
        rel_path = os.path.relpath(file_path, self.base_dir)
        parts = rel_path.split(os.sep)
        if len(parts) > 1:
            path_html = []
            for part in parts[:-1]:
                path_html.append(f'<span class="path-part">{html.escape(part)}</span>')
                path_html.append('<span class="path-separator">/</span>')
            path_html.append(f'<span class="path-file">{html.escape(parts[-1])}</span>')
            return "".join(path_html)
        return f'<span class="path-file">{html.escape(rel_path)}</span>'

    def is_whitespace_only_change(self, original, corrected):
        orig_no_space = "".join(original.split())
        corr_no_space = "".join(corrected.split())
        return orig_no_space == corr_no_space

    def clean_placeholder_text(self, text):
        text = re.sub(r"__WHITELIST_\d+__", "", text)
        text = re.sub(r"__\w+_\d+__", "", text)
        return text

    def highlight_diff(self, orig_text, corrected_text, is_whitespace_change=False):
        orig_text = self.clean_placeholder_text(orig_text)
        corrected_text = self.clean_placeholder_text(corrected_text)

        orig_chars = list(html.escape(orig_text))
        corrected_chars = list(html.escape(corrected_text))

        matcher = difflib.SequenceMatcher(None, orig_chars, corrected_chars)

        orig_html = []
        corrected_html = []

        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                orig_html.append("".join(orig_chars[i1:i2]))
                corrected_html.append("".join(corrected_chars[j1:j2]))
            elif op == "delete":
                span_class = "whitespace-change" if is_whitespace_change else "diff-delete"
                orig_html.append(f'<span class="{span_class}">{"".join(orig_chars[i1:i2])}</span>')
            elif op == "insert":
                span_class = "whitespace-change" if is_whitespace_change else "diff-add"
                corrected_html.append(
                    f'<span class="{span_class}">{"".join(corrected_chars[j1:j2])}</span>'
                )
            elif op == "replace":
                span_class_delete = "whitespace-change" if is_whitespace_change else "diff-delete"
                span_class_add = "whitespace-change" if is_whitespace_change else "diff-add"
                orig_html.append(
                    f'<span class="{span_class_delete}">{"".join(orig_chars[i1:i2])}</span>'
                )
                corrected_html.append(
                    f'<span class="{span_class_add}">{"".join(corrected_chars[j1:j2])}</span>'
                )

        return "".join(orig_html), "".join(corrected_html)

    def generate_report(
        self,
        all_files_result,
        output_path: str = "report.html",
        fp_manager=None,
        stats_data=None,
        model_info="1.5B parameters",
        filter_false_positives=True,
    ):
        total_files = len(all_files_result)
        total_changes = 0
        total_chars = 0
        total_whitespace_changes = 0
        valid_changes = 0

        if stats_data:
            total_files = stats_data.get("total_files", total_files)
            total_changes = stats_data.get("total_changes", 0)
            valid_changes = stats_data.get("valid_changes", 0)
            total_whitespace_changes = stats_data.get("total_whitespace_changes", 0)
            total_chars = stats_data.get("total_chars", 0)
        else:
            for file_item in all_files_result:
                for line_info in file_item["lines"]:
                    if line_info["original"] != line_info["corrected"]:
                        total_changes += 1
                        if fp_manager and not fp_manager.is_false_positive(
                            line_info["original"], line_info["corrected"]
                        ):
                            valid_changes += 1
                        elif not fp_manager:
                            valid_changes += 1
                        if self.is_whitespace_only_change(
                            line_info["original"], line_info["corrected"]
                        ):
                            total_whitespace_changes += 1
                    total_chars += len(line_info["original"])

        defect_rate_per_thousand = (valid_changes / max(1, total_chars)) * 1000

        template = HTMLTemplate()

        stats_data = {
            "total_files": total_files,
            "valid_changes": valid_changes,
            "total_changes": total_changes,
            "total_chars": total_chars,
            "total_whitespace_changes": total_whitespace_changes,
            "defect_rate_per_thousand": defect_rate_per_thousand,
        }

        files_content = self._generate_files_content(
            all_files_result, fp_manager if filter_false_positives else None
        )

        html_content = template.generate_full_html(stats_data, files_content, model_info)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # The CLI prints the path as its result; this is the library-side trace.
        logger.debug("report generated: %s", output_path)
        return output_path

    def _generate_files_content(self, all_files_result, fp_manager=None):
        content_parts = []

        for file_item in all_files_result:
            file_path = file_item["file"]
            lines_info = file_item["lines"]
            line_map = file_item["line_map"]

            modified_lines = [
                (idx, info)
                for idx, info in enumerate(lines_info)
                if info["corrected"] != info["original"]
            ]

            if not modified_lines:
                continue

            content_parts.append("<div class='file-section'>")
            content_parts.append(f"<h2>{self.format_path_for_display(file_path)}</h2>")
            content_parts.append("<table class='diff-table'>")
            content_parts.append("<tr><th>Line</th><th>Original</th><th>Corrected</th></tr>")

            for idx, info in modified_lines:
                is_whitespace_change = self.is_whitespace_only_change(
                    info["original"], info["corrected"]
                )

                highlighted_orig, highlighted_corrected = self.highlight_diff(
                    info["original"], info["corrected"], is_whitespace_change
                )

                source_badge = ""
                review_source = info.get("review_source")
                if review_source and review_source != "unknown":
                    rule_ids = ", ".join(info.get("rule_ids", []))
                    title = f" title='{html.escape(rule_ids, quote=True)}'" if rule_ids else ""
                    source_badge = (
                        f"<span class='source-badge text-source'{title}>"
                        f"{html.escape(review_source)}</span>"
                    )
                    severity = info.get("severity", "suggestion")
                    source_badge += (
                        f"<span class='source-badge code-source'>{html.escape(severity)}</span>"
                    )
                elif "from_code_block" in info:
                    if info["from_code_block"]:
                        source_badge = "<span class='source-badge code-source'>code comment</span>"
                    else:
                        source_badge = "<span class='source-badge text-source'>plain text</span>"

                llm_verdict_info = info.get("llm_verdict") or {}
                llm_verdict = llm_verdict_info.get("verdict")
                if llm_verdict in ("confirmed", "rejected", "skipped", "error"):
                    reason = html.escape(llm_verdict_info.get("reason", ""), quote=True)
                    if llm_verdict in ("confirmed", "rejected"):
                        confidence = llm_verdict_info.get("confidence", 0)
                        llm_title = f"confidence {confidence}; {reason}"
                    else:
                        # No verdict was reached, so a confidence number would lie.
                        llm_title = reason
                    source_badge += (
                        f"<span class='source-badge llm-source llm-{llm_verdict}' "
                        f"title='{html.escape(llm_title, quote=True)}'>"
                        f"llm: {llm_verdict}</span>"
                    )

                is_false_positive = fp_manager and fp_manager.is_false_positive(
                    info["original"], info["corrected"]
                )

                row_digest = hashlib.sha256(f"{file_item['file']}:{idx}".encode()).hexdigest()[:16]
                row_id = f"row_{row_digest}"
                row_classes = []
                if is_whitespace_change:
                    row_classes.append("whitespace-row")
                if is_false_positive:
                    row_classes.append("false-positive-row")
                if llm_verdict == "rejected":
                    row_classes.append("llm-rejected-row")
                row_class = " ".join(row_classes)
                content_parts.append(f"<tr id='{row_id}' class='{row_class}'>")
                content_parts.append(f"<td>{html.escape(str(line_map[idx]))}</td>")
                content_parts.append(f"<td>{source_badge}{highlighted_orig}")

                action = "unmark" if is_false_positive else "mark"
                label = "Unmark false positive" if is_false_positive else "Mark as false positive"
                marked_class = " marked" if is_false_positive else ""
                content_parts.append(
                    f'<button class="false-positive-btn{marked_class}" '
                    f'data-fp-action="{action}" data-row-id="{row_id}" '
                    f'data-original="{html.escape(info["original"], quote=True)}" '
                    f'data-corrected="{html.escape(info["corrected"], quote=True)}">'
                    f"{label}</button>"
                )

                content_parts.append("</td>")
                content_parts.append(f"<td>{highlighted_corrected}</td>")
                content_parts.append("</tr>")

            content_parts.append("</table>")
            content_parts.append("</div>")

        return "\n".join(content_parts)
