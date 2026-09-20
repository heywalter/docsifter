"""Review orchestration: one DocumentReviewer coordinates rules, models, and reports."""

import logging
import os
import re
import threading
import time
from typing import Any, Dict

from .config import ConfigManager
from .corrector import FalsePositiveManager, TextCorrector
from .file_processor import FileProcessor
from .github_integration import GitHubIntegration, GitHubTaskManager
from .history_manager import HistoryManager, TaskStatus
from .html_generator import HTMLGenerator
from .llm_reviewer import (
    load_context_reviewer,
    load_llm_reviewer,
    review_context_as_changes,
)
from .observability import record_review
from .runtime import get_runtime_path

logger = logging.getLogger(__name__)

WEB_ALLOWED_MODELS = {
    "rule-based",
    "shibing624/chinese-text-correction-1.5b",
    "shibing624/chinese-text-correction-7b",
}

REMOTE_MODEL_BACKENDS = {"ollama", "openai"}


def is_model_allowed(text_corrector, model: str) -> bool:
    """Local backends only accept the curated model list; remote backends accept any model id."""
    if model in WEB_ALLOWED_MODELS:
        return True
    return getattr(text_corrector, "backend_kind", "local") in REMOTE_MODEL_BACKENDS


class DocumentReviewer:
    def __init__(self, config_file: str | None = None, server_mode: bool = False):
        self.config_manager = ConfigManager(config_file)
        self.config = self.config_manager.get_config()
        self.server_mode = server_mode

        self.file_processor = FileProcessor(
            self.config["skip_file_patterns"],
            max_file_size_mb=self.config.get("max_file_size_mb"),
        )
        self.text_corrector = TextCorrector(self.config, server_mode=server_mode)
        self.false_positive_manager = FalsePositiveManager()
        self.html_generator = HTMLGenerator()
        self.history_manager = HistoryManager()

        self.github_integration = GitHubIntegration(self.config)
        self.github_task_manager = GitHubTaskManager(self.github_integration)
        # The small-model client and legacy result buffers are mutable. A single
        # worker keeps reports, statistics, and model selection isolated by task.
        self.review_lock = threading.RLock()

        self.stats = {
            "total_files": 0,
            "total_changes": 0,
            "valid_changes": 0,
            "total_whitespace_changes": 0,
            "total_chars": 0,
            "defect_rate_per_thousand": 0.0,
        }

        self.results = []
        self._context_files_reviewed = 0

    def update_model(self, model_name: str):
        with self.review_lock:
            try:
                self.text_corrector.update_model(model_name)
                logger.info("model updated: %s", model_name)
            except Exception as e:
                logger.error("failed to update model: %s", e)
                raise

    def use_rule_based_mode(self):
        """Disable local model correction and use rule preview checks only."""
        with self.review_lock:
            self.text_corrector.use_rule_based_mode()

    def _configure_review_mode(self, model: str | None) -> None:
        if model and model != "rule-based":
            self.update_model(model)
        else:
            self.use_rule_based_mode()

    def run_local_review(
        self,
        directory: str,
        debug: bool = False,
        task_id: str | None = None,
        model: str | None = "rule-based",
        auto_generate: bool = True,
        output_file: str | None = None,
    ) -> Dict[str, Any]:
        """Run one local review atomically, including report generation."""
        with self.review_lock:
            if task_id and self.history_manager.is_task_cancelled(task_id):
                return {"cancelled": True, "stats": self.stats, "results": []}

            self._configure_review_mode(model)
            model_enabled = self.text_corrector.ai_correction_enabled
            try:
                result = self.process_directory(directory, debug=debug, task_id=task_id)
                if result.get("cancelled"):
                    return result

                # Optional second pass: let the configured LLM validate
                # small-model findings before the report is generated.
                llm_reviewer = load_llm_reviewer(self.config_manager)
                if llm_reviewer:
                    try:
                        result["llm_review"] = llm_reviewer.apply(self.results, debug=debug)
                    except Exception as e:
                        logger.warning("LLM review skipped: %s", e)

                result["review_backend"] = (
                    self.text_corrector.current_model if model_enabled else "rule-based"
                )
                result["model_loaded"] = bool(model_enabled and self.text_corrector.gpt_client)

                result["report_generated"] = False
                if auto_generate:
                    report_path = output_file or get_runtime_path(
                        "reports", f"{task_id or 'local-review'}.html"
                    )
                    try:
                        html_file = self.generate_html_report(
                            report_path, filter_false_positives=True
                        )
                        result["report_generated"] = True
                        result["report_path"] = html_file
                        if task_id:
                            self.history_manager.set_report_path(task_id, html_file)
                            message = (
                                f"Filtered report generated: {html_file}"
                                if self.results
                                else f"Report generated (no issues found): {html_file}"
                            )
                            self.history_manager.add_log(task_id, "INFO", message)

                            full_report_file = get_runtime_path(
                                "reports", f"local-{task_id}-full.html"
                            )
                            self.generate_html_report(
                                full_report_file, filter_false_positives=False
                            )
                            self.history_manager.add_log(
                                task_id, "INFO", f"Full report generated: {full_report_file}"
                            )
                    except Exception as e:
                        if task_id:
                            self.history_manager.add_log(
                                task_id, "ERROR", f"Report generation failed: {str(e)}"
                            )

                return result
            finally:
                self.text_corrector.release_model()
                if task_id and model_enabled:
                    self.history_manager.add_log(task_id, "INFO", "Model resources released")

    def run_github_review(self, task_id: str, model: str | None = "rule-based") -> Dict[str, Any]:
        """Run one GitHub review while keeping the model client task-local in effect."""
        with self.review_lock:
            try:
                self._configure_review_mode(model)
                result = self.github_task_manager.execute_github_task(task_id, self)
                result["review_backend"] = (
                    self.text_corrector.current_model
                    if self.text_corrector.ai_correction_enabled
                    else "rule-based"
                )
                return result
            except Exception as e:
                self.github_task_manager.mark_task_failed(task_id, str(e))
                raise
            finally:
                self.text_corrector.release_model()

    def get_model_info(self) -> str:
        if self.text_corrector.model_init_failed:
            return "Model unavailable"
        if hasattr(self.text_corrector, "current_model") and self.text_corrector.current_model:
            if not self.text_corrector.ai_correction_enabled:
                return "Rule preview mode"
            model_name = self.text_corrector.current_model
            if "1.5b" in model_name.lower():
                return "1.5B parameters"
            elif "7b" in model_name.lower():
                return "7B parameters"
            else:
                return f"Custom model: {model_name}"
        return "1.5B parameters"

    def process_directory(
        self, directory: str, debug: bool = False, task_id: str = None
    ) -> Dict[str, Any]:
        logger.info("processing directory: %s", directory)
        started_at = time.monotonic()
        context_reviewer = load_context_reviewer(self.config_manager)
        context_max_files = int(self.config.get("context_max_files") or 0)
        context_scope = str(self.config.get("context_review_scope") or "flagged").lower()
        self._context_files_reviewed = 0
        if context_reviewer:
            logger.info(
                "context review enabled: checking cross-line issues in %s "
                "(at most %s file(s) this run)",
                "every file" if context_scope == "all" else "files with findings",
                context_max_files,
            )

        if task_id:
            if self.history_manager.is_task_cancelled(task_id):
                return {"cancelled": True, "stats": self.stats, "results": []}
            self.history_manager.update_task_status(task_id, TaskStatus.RUNNING)
            self.history_manager.add_log(task_id, "INFO", f"Started processing: {directory}")

        self.stats = {
            "total_files": 0,
            "total_changes": 0,
            "valid_changes": 0,
            "total_whitespace_changes": 0,
            "total_chars": 0,
            "defect_rate_per_thousand": 0.0,
        }
        self.results = []

        supported_files = list(self.file_processor.scan_directory(directory))
        total_files = len(supported_files)

        if task_id:
            self.history_manager.add_log(task_id, "INFO", f"Found {total_files} files to process")

        for i, (file_path, content) in enumerate(supported_files):
            if task_id and self.history_manager.is_task_cancelled(task_id):
                logger.info("task cancelled, stopping")
                if task_id:
                    self.history_manager.add_log(task_id, "INFO", "Task processing interrupted")
                record_review(self.stats, time.monotonic() - started_at, cancelled=True)
                return {
                    "total_files": self.stats["total_files"],
                    "total_changes": self.stats["total_changes"],
                    "valid_changes": self.stats["valid_changes"],
                    "total_whitespace_changes": self.stats["total_whitespace_changes"],
                    "total_chars": self.stats["total_chars"],
                    "defect_rate_per_thousand": self.stats["defect_rate_per_thousand"],
                    "cancelled": True,
                }

            logger.info("processing file: %s", file_path)

            if task_id:
                progress = int((i / total_files) * 100) if total_files > 0 else 0
                self.history_manager.update_progress(
                    task_id, progress, file_path, f"File {i + 1}/{total_files}"
                )
                self.history_manager.add_log(task_id, "INFO", f"Processing: {file_path}")

            self.stats["total_files"] += 1

            extracted_texts = self.text_corrector.extract_text_from_file(file_path, content)
            for _, _, extracted_text in extracted_texts:
                self.stats["total_chars"] += len(extracted_text)

            changes = self.text_corrector.process_file(file_path, content, debug=debug)

            if changes:
                self.stats["total_changes"] += len(changes)
                valid_changes = []
                whitespace_changes = 0

                for change in changes:
                    if not self.false_positive_manager.is_false_positive(
                        change["original_text"], change["corrected_text"]
                    ):
                        if self._is_whitespace_change(
                            change["original_text"], change["corrected_text"]
                        ):
                            change["is_whitespace"] = True
                            whitespace_changes += 1
                        else:
                            change["is_whitespace"] = False

                        valid_changes.append(change)

                if valid_changes:
                    self.results.append({"file_path": file_path, "changes": valid_changes})

                    self.stats["valid_changes"] += len(valid_changes)
                    self.stats["total_whitespace_changes"] += whitespace_changes

            # Under the default "flagged" scope this layer follows findings like
            # the rest of the pipeline; it sends a whole document per request, so
            # reviewing every file costs orders of magnitude more than the
            # per-finding pass and ignores what the local model already did.
            file_was_flagged = any(r["file_path"] == file_path for r in self.results)
            context_changes = (
                self._run_context_review(context_reviewer, file_path, extracted_texts, debug=debug)
                if context_scope == "all" or file_was_flagged
                else []
            )
            if context_changes:
                existing = next((r for r in self.results if r["file_path"] == file_path), None)
                if existing is None:
                    self.results.append({"file_path": file_path, "changes": context_changes})
                else:
                    existing["changes"].extend(context_changes)
                self.stats["valid_changes"] += len(context_changes)

        if self.stats["total_chars"] > 0:
            self.stats["defect_rate_per_thousand"] = (
                self.stats["valid_changes"] / self.stats["total_chars"] * 1000
            )

        logger.info(
            "review finished: %s file(s), %s correction(s)",
            self.stats["total_files"],
            self.stats["valid_changes"],
        )
        duration_seconds = time.monotonic() - started_at
        record_review(self.stats, duration_seconds)
        logger.info(
            "review completed directory=%s files=%s findings=%s duration=%.3fs",
            directory,
            self.stats["total_files"],
            self.stats["valid_changes"],
            duration_seconds,
        )

        if task_id:
            self.history_manager.update_progress(task_id, 100, None, "Done")
            self.history_manager.update_task_stats(task_id, self.stats)
            self.history_manager.save_task_results(task_id, self.results)
            self.history_manager.add_log(
                task_id,
                "INFO",
                f"Done: {self.stats['total_files']} files, "
                f"{self.stats['valid_changes']} corrections",
            )

        return {"stats": self.stats, "results": self.results}

    def _is_whitespace_change(self, original: str, corrected: str) -> bool:
        original_no_space = re.sub(r"\s+", "", original)
        corrected_no_space = re.sub(r"\s+", "", corrected)
        return original_no_space == corrected_no_space

    def _run_context_review(
        self, context_reviewer, file_path: str, extracted_texts: list, debug: bool = False
    ) -> list:
        """Ask the optional LLM reviewer for cross-line issues in one file."""
        if context_reviewer is None or not extracted_texts:
            return []

        context_max_files = int(self.config.get("context_max_files") or 0)
        if context_max_files and self._context_files_reviewed >= context_max_files:
            if self._context_files_reviewed == context_max_files:
                logger.warning(
                    "context review budget reached (%s file(s)); remaining files are "
                    "not context-reviewed. Raise context_max_files to cover them.",
                    context_max_files,
                )
                self._context_files_reviewed += 1
            return []
        self._context_files_reviewed += 1

        numbered_lines = [(line_no, plain) for line_no, _, plain in extracted_texts]
        return review_context_as_changes(context_reviewer, file_path, numbered_lines, debug=debug)

    def generate_html_report(
        self, output_file: str = "report.html", filter_false_positives: bool = True
    ) -> str:
        logger.info("generating HTML report: %s", output_file)

        all_files_result = []
        for result in self.results:
            lines = []
            for change in result["changes"]:
                line_info = {
                    "original": change["original_text"],
                    "corrected": change["corrected_text"],
                    "line_number": change.get("line_number", 0),
                    "is_whitespace": change.get("is_whitespace", False),
                    "review_source": change.get("review_source", "unknown"),
                    "severity": change.get("severity", "suggestion"),
                    "rule_ids": change.get("rule_ids", []),
                    "llm_verdict": change.get("llm_verdict"),
                }
                lines.append(line_info)

            line_map = {}
            for i, change in enumerate(result["changes"]):
                line_map[i] = change.get("line_number", i + 1)

            file_item = {"file": result["file_path"], "lines": lines, "line_map": line_map}
            all_files_result.append(file_item)

        self.html_generator.base_dir = os.getcwd()

        model_info = self.get_model_info()
        return self.html_generator.generate_report(
            all_files_result,
            output_file,
            self.false_positive_manager,
            self.stats,
            model_info,
            filter_false_positives,
        )

    def format_stats(self) -> str:
        """Render the run's statistics as the block the CLI prints.

        Returned rather than printed: this module narrates through the logger so
        that DOCSIFTER_LOG_FORMAT=json stays parseable, and the entry point
        decides where a human-facing summary goes.
        """
        average = self.stats["valid_changes"] / max(1, self.stats["total_files"])
        return "\n".join(
            [
                "",
                "=== Stats ===",
                f"Files scanned: {self.stats['total_files']}",
                f"Total changes: {self.stats['total_changes']}",
                f"Valid changes: {self.stats['valid_changes']}",
                f"Whitespace-only changes: {self.stats['total_whitespace_changes']}",
                f"Characters reviewed: {self.stats['total_chars']:,}",
                f"Changes per file (avg): {average:.1f}",
                f"Defect rate: {self.stats['defect_rate_per_thousand']:.1f}‰",
            ]
        )

    def update_config(self, key: str, value: Any):
        with self.review_lock:
            self.config_manager.update_config(key, value)
            self.config = self.config_manager.get_config()

            if key in ["skip_file_patterns", "max_file_size_mb"]:
                self.file_processor = FileProcessor(
                    self.config["skip_file_patterns"],
                    max_file_size_mb=self.config.get("max_file_size_mb"),
                )

            if key in ["whitelist", "forced_fixes", "skip_text_patterns"]:
                self.text_corrector = TextCorrector(self.config, server_mode=self.server_mode)
