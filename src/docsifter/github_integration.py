"""GitHub webhook verification and pull request review integration."""

import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Dict, List

import requests

from .llm_reviewer import (
    load_context_reviewer,
    load_llm_reviewer,
    review_context_as_changes,
)
from .runtime import get_runtime_path, utcnow


class GitHubIntegration:
    """Clone repositories and read pull request metadata from the GitHub API.

    Every clone lands in a temporary directory that this object owns and
    removes; nothing is written into the user's working tree.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.github_token = self.config.get("github_token", "")
        self.temp_dir = None
        self._owns_temp_dir = False

    def _git_environment(self) -> Dict[str, str]:
        """Build the environment for a git subprocess.

        The token is passed as an ``extraHeader`` through GIT_CONFIG_* rather
        than embedded in the clone URL, so it does not end up in the remote
        configuration, in ``git remote -v`` output or in process listings.
        ``GIT_TERMINAL_PROMPT=0`` keeps a private repository from hanging on
        a credential prompt.
        """
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        if self.github_token:
            credential = base64.b64encode(f"x-access-token:{self.github_token}".encode()).decode(
                "ascii"
            )
            config_index = int(env.get("GIT_CONFIG_COUNT", "0"))
            env["GIT_CONFIG_COUNT"] = str(config_index + 1)
            env[f"GIT_CONFIG_KEY_{config_index}"] = "http.https://github.com/.extraHeader"
            env[f"GIT_CONFIG_VALUE_{config_index}"] = f"Authorization: Basic {credential}"
        return env

    def parse_github_url(self, url: str) -> Dict[str, str]:
        """Split a repository, tree, blob or pull request URL into its parts."""
        patterns = [
            r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/?(.*)$",
            r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/?(.*)$",
            r"https://github\.com/([^/]+)/([^/]+)/?$",
            r"git@github\.com:([^/]+)/([^/]+)\.git$",
        ]

        for pattern in patterns:
            match = re.match(pattern, url.strip())
            if match:
                groups = match.groups()
                result = {
                    "owner": groups[0],
                    "repo": groups[1].replace(".git", ""),
                    "branch": groups[2] if len(groups) > 2 and groups[2] else "main",
                    "path": groups[3] if len(groups) > 3 and groups[3] else "",
                }
                return result

        raise ValueError(f"Cannot parse GitHub URL: {url}")

    def clone_repository(self, url: str, target_dir: str = None, ref: str = None) -> str:
        """Clone ``url`` shallowly and return the checkout path.

        With ``ref`` the exact revision is fetched, which is what pins a pull
        request review to the head commit that triggered it rather than to
        whatever the branch points at by the time the review runs.
        """
        repo_info = self.parse_github_url(url)
        requested_ref = ref

        if not target_dir:
            if not self.temp_dir:
                self.temp_dir = tempfile.mkdtemp(prefix="docsifter_github_")
                self._owns_temp_dir = True
            ref_digest = hashlib.sha256((requested_ref or "default").encode("utf-8")).hexdigest()[
                :12
            ]
            target_dir = os.path.join(
                self.temp_dir,
                f"{repo_info['owner']}_{repo_info['repo']}_{ref_digest}",
            )

        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)

        clone_url = f"https://github.com/{repo_info['owner']}/{repo_info['repo']}.git"
        try:
            if requested_ref:
                os.makedirs(target_dir, exist_ok=True)
                subprocess.run(
                    ["git", "init"],
                    cwd=target_dir,
                    env=self._git_environment(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "remote", "add", "origin", clone_url],
                    cwd=target_dir,
                    env=self._git_environment(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "fetch", "--depth", "1", "origin", requested_ref],
                    cwd=target_dir,
                    env=self._git_environment(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "checkout", "--detach", "FETCH_HEAD"],
                    cwd=target_dir,
                    env=self._git_environment(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["git", "clone", "--depth", "1", clone_url, target_dir],
                    env=self._git_environment(),
                    check=True,
                    capture_output=True,
                    text=True,
                )
            return target_dir
        except subprocess.CalledProcessError as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise Exception(f"Failed to clone repository: {e.stderr}") from e

    def get_pr_changed_files(self, owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
        """List the files a pull request touches, so the review stays scoped to them."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        headers = {}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        try:
            files = []
            page = 1
            while True:
                response = requests.get(
                    url,
                    headers=headers,
                    params={"per_page": 100, "page": page},
                    timeout=30,
                )
                response.raise_for_status()
                page_files = response.json()
                files.extend(page_files)
                if len(page_files) < 100:
                    break
                page += 1

            supported_extensions = {".adoc", ".asciidoc", ".asc", ".txt", ".md", ".markdown"}
            filtered_files = []

            for file in files:
                file_path = file["filename"]
                if any(file_path.endswith(ext) for ext in supported_extensions):
                    filtered_files.append(
                        {
                            "filename": file["filename"],
                            "status": file["status"],  # added, modified, removed
                            "additions": file.get("additions", 0),
                            "deletions": file.get("deletions", 0),
                            "changes": file.get("changes", 0),
                        }
                    )

            return filtered_files
        except requests.RequestException as e:
            if hasattr(e, "response") and e.response is not None and e.response.status_code == 403:
                if "rate limit" in str(e).lower():
                    if not self.github_token:
                        raise Exception(
                            "GitHub API rate limit exceeded. Configure a GitHub Token in settings for a higher limit."
                        ) from e
                    else:
                        raise Exception(
                            "GitHub API rate limit exceeded. Try again later or check your token quota."
                        ) from e
            raise Exception(f"Failed to fetch PR changed files: {e}") from e

    def cleanup(self):
        """Remove the temporary checkout, if this object created it."""
        if self._owns_temp_dir and self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.temp_dir = None
        self._owns_temp_dir = False

    def __del__(self):
        try:
            self.cleanup()
        except AttributeError:
            pass


class GitHubTaskManager:
    """Run pull request reviews as tracked, cancellable background tasks.

    Task state lives in memory behind ``_tasks_lock``; the durable record of a
    review is the history row written by the webhook routes.
    """

    def __init__(self, github_integration: GitHubIntegration):
        self.github = github_integration
        self.active_tasks = {}
        self._tasks_lock = threading.RLock()

    def create_github_task(
        self,
        repo_url: str,
        directories: List[str],
        check_all: bool = False,
        pr_number: int = None,
        ref: str = None,
    ) -> str:
        """Register a pull request review task and return its id.

        ``ref`` pins the review to one revision; ``pr_number`` limits it to
        that pull request's changed files unless ``check_all`` is set.
        """
        task_id = f"github_{utcnow().strftime('%Y%m%d_%H%M%S_%f')}"

        task_info = {
            "id": task_id,
            "type": "github",
            "repo_url": repo_url,
            "directories": directories,
            "check_all": check_all,
            "pr_number": pr_number,
            "ref": ref,
            "status": "created",
            "created_at": utcnow().isoformat(),
            "local_path": None,
            "files_to_check": [],
            "logs": [],
            "progress": 0,
            "stats": {},
            "report_path": None,
        }

        with self._tasks_lock:
            self.active_tasks[task_id] = task_info
        return task_id

    def execute_github_task(self, task_id: str, document_reviewer) -> Dict[str, Any]:
        """Clone, review the changed files, and produce the report for one task.

        Checks for cancellation between stages so a task stopped from the Web
        UI does not keep cloning or reviewing.
        """
        with self._tasks_lock:
            if task_id not in self.active_tasks:
                raise ValueError(f"Task not found: {task_id}")
            task = self.active_tasks[task_id]

        try:
            if self.is_task_cancelled(task_id):
                return self._cancelled_result(task_id)

            task["status"] = "cloning"
            self.add_task_log(task_id, "INFO", "Cloning GitHub repository")

            repo_info = self.github.parse_github_url(task["repo_url"])
            local_path = self.github.clone_repository(task["repo_url"], ref=task.get("ref"))
            task["local_path"] = local_path

            if self.is_task_cancelled(task_id):
                return self._cancelled_result(task_id)

            files_to_check = []

            if task["pr_number"] and not task["check_all"]:
                changed_files = self.github.get_pr_changed_files(
                    repo_info["owner"], repo_info["repo"], task["pr_number"]
                )

                for file_info in changed_files:
                    file_path = os.path.join(local_path, file_info["filename"])
                    if os.path.exists(file_path):
                        files_to_check.append(file_path)

            elif task["check_all"]:
                directories = task["directories"] or ["."]
                for directory in directories:
                    dir_path = os.path.join(local_path, directory)
                    if os.path.exists(dir_path):
                        files = document_reviewer.file_processor.get_all_supported_files(dir_path)
                        files_to_check.extend(files)

            else:
                for directory in task["directories"]:
                    dir_path = os.path.join(local_path, directory)
                    if os.path.exists(dir_path):
                        files = document_reviewer.file_processor.get_all_supported_files(dir_path)
                        files_to_check.extend(files)

            task["files_to_check"] = files_to_check
            task["status"] = "processing"
            task["message"] = f"Found {len(files_to_check)} files to process"
            self.add_task_log(task_id, "INFO", task["message"])

            results = []
            total_files = len(files_to_check)
            stats = {
                "total_files": 0,
                "total_changes": 0,
                "valid_changes": 0,
                "total_whitespace_changes": 0,
                "total_chars": 0,
                "defect_rate_per_thousand": 0.0,
            }
            # Webhook reviews are unattended, so both optional LLM layers stay off
            # here unless pr_llm_enabled is explicitly turned on, even when the
            # layers themselves are enabled for CLI and Web reviews.
            # document_reviewer is duck-typed here, as with the collaborators below.
            reviewer_config = getattr(document_reviewer, "config", None) or {}
            config_manager = getattr(document_reviewer, "config_manager", None)
            pr_llm_enabled = bool(reviewer_config.get("pr_llm_enabled")) and config_manager
            context_reviewer = load_context_reviewer(config_manager) if pr_llm_enabled else None
            context_max_files = int(reviewer_config.get("context_max_files") or 0)
            context_scope = str(reviewer_config.get("context_review_scope") or "flagged").lower()
            context_files_reviewed = 0
            if context_reviewer:
                self.add_task_log(
                    task_id,
                    "INFO",
                    "Context review enabled for this pull request, covering "
                    f"{'every changed file' if context_scope == 'all' else 'files with findings'} "
                    f"(at most {context_max_files} file(s))",
                )

            fp_manager = getattr(document_reviewer, "false_positive_manager", None)
            is_whitespace_change = getattr(
                document_reviewer,
                "_is_whitespace_change",
                lambda original, corrected: "".join(original.split()) == "".join(corrected.split()),
            )

            for i, file_path in enumerate(files_to_check):
                if self.is_task_cancelled(task_id):
                    return self._cancelled_result(task_id, stats)

                progress = int(((i + 1) / max(1, total_files)) * 100)
                task["progress"] = progress
                task["message"] = (
                    f"Processing file {i + 1}/{total_files}: {os.path.relpath(file_path, local_path)}"
                )

                content = document_reviewer.file_processor.read_file_content(file_path)
                if content:
                    stats["total_files"] += 1
                    extracted_texts = document_reviewer.text_corrector.extract_text_from_file(
                        file_path, content
                    )
                    for _, _, extracted_text in extracted_texts:
                        stats["total_chars"] += len(extracted_text)

                    changes = document_reviewer.text_corrector.process_file(file_path, content)

                    stats["total_changes"] += len(changes)
                    valid_changes = []
                    whitespace_changes = 0
                    for change in changes:
                        is_false_positive = fp_manager and fp_manager.is_false_positive(
                            change["original_text"], change["corrected_text"]
                        )
                        if is_false_positive:
                            continue

                        change["is_whitespace"] = is_whitespace_change(
                            change["original_text"], change["corrected_text"]
                        )
                        if change["is_whitespace"]:
                            whitespace_changes += 1
                        valid_changes.append(change)

                    # A whole document goes out per request here, so under the
                    # default "flagged" scope this follows findings like the rest
                    # of the pipeline rather than the changed-file count.
                    context_changes = []
                    wanted = context_scope == "all" or bool(valid_changes)
                    if context_reviewer and wanted:
                        if context_max_files and context_files_reviewed >= context_max_files:
                            if context_files_reviewed == context_max_files:
                                self.add_task_log(
                                    task_id,
                                    "INFO",
                                    f"Context review budget reached ({context_max_files} "
                                    "file(s)); remaining files are not context-reviewed",
                                )
                                context_files_reviewed += 1
                        else:
                            context_files_reviewed += 1
                            context_changes = review_context_as_changes(
                                context_reviewer,
                                file_path,
                                [(line_no, plain) for line_no, _, plain in extracted_texts],
                            )

                    # Context findings bypass the false-positive filter, matching
                    # the local review path.
                    valid_changes.extend(context_changes)

                    if valid_changes:
                        relative_path = os.path.relpath(file_path, local_path)
                        results.append(
                            {
                                "file_path": relative_path,
                                "full_path": file_path,
                                "changes": valid_changes,
                                "corrections": valid_changes,
                            }
                        )
                        stats["valid_changes"] += len(valid_changes)
                        stats["total_whitespace_changes"] += whitespace_changes

            if stats["total_chars"] > 0:
                stats["defect_rate_per_thousand"] = (
                    stats["valid_changes"] / stats["total_chars"] * 1000
                )

            if pr_llm_enabled:
                llm_reviewer = load_llm_reviewer(config_manager)
                if llm_reviewer:
                    try:
                        summary = llm_reviewer.apply(results)
                        self.add_task_log(
                            task_id,
                            "INFO",
                            f"LLM review: {summary['reviewed']} verified "
                            f"({summary['confirmed']} confirmed, {summary['rejected']} rejected), "
                            f"{summary['skipped']} over budget, {summary['errors']} failed",
                        )
                    except Exception as e:
                        self.add_task_log(task_id, "WARNING", f"LLM review skipped: {e}")

            report_path = self._generate_task_report(
                task_id, local_path, results, stats, document_reviewer
            )

            task["status"] = "completed"
            task["results"] = results
            task["stats"] = stats
            task["report_path"] = report_path
            task["progress"] = 100
            task["message"] = "GitHub document review completed"
            task["completed_at"] = utcnow().isoformat()
            self.add_task_log(task_id, "INFO", task["message"])

            return {
                "success": True,
                "task_id": task_id,
                "total_files": total_files,
                "files_with_issues": len(results),
                "results": results,
                "stats": stats,
                "report_path": report_path,
            }

        except Exception as e:
            task["status"] = "failed"
            task["error"] = str(e)
            task["failed_at"] = utcnow().isoformat()
            self.add_task_log(task_id, "ERROR", f"GitHub document review failed: {str(e)}")
            raise
        finally:
            cleanup = getattr(self.github, "cleanup", None)
            if cleanup:
                cleanup()

    def _generate_task_report(
        self,
        task_id: str,
        local_path: str,
        results: List[Dict[str, Any]],
        stats: Dict[str, Any],
        document_reviewer,
    ) -> str | None:
        html_generator = getattr(document_reviewer, "html_generator", None)
        if not html_generator:
            return None

        all_files_result = []
        for result in results:
            lines = []
            line_map = {}
            for index, change in enumerate(result["changes"]):
                lines.append(
                    {
                        "original": change["original_text"],
                        "corrected": change["corrected_text"],
                        "line_number": change.get("line_number", 0),
                        "is_whitespace": change.get("is_whitespace", False),
                        "review_source": change.get("review_source", "unknown"),
                        "severity": change.get("severity", "suggestion"),
                        "rule_ids": change.get("rule_ids", []),
                        "llm_verdict": change.get("llm_verdict"),
                    }
                )
                line_map[index] = change.get("line_number", index + 1)

            all_files_result.append(
                {"file": result["file_path"], "lines": lines, "line_map": line_map}
            )

        report_path = get_runtime_path("reports", f"{task_id}.html")
        html_generator.base_dir = local_path
        model_info = (
            document_reviewer.get_model_info()
            if hasattr(document_reviewer, "get_model_info")
            else "1.5B parameters"
        )
        html_generator.generate_report(
            all_files_result,
            report_path,
            getattr(document_reviewer, "false_positive_manager", None),
            stats,
            model_info,
            True,
        )
        return report_path

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Return the task record, or an error dict when it is unknown."""
        with self._tasks_lock:
            if task_id not in self.active_tasks:
                return {"error": "Task not found"}

            task = self.active_tasks[task_id]
            snapshot = dict(task)
            snapshot["logs"] = list(task.get("logs", []))
            return snapshot

    def add_task_log(self, task_id: str, level: str, message: str) -> None:
        """Append one line to a task's log, ignoring unknown task ids."""
        with self._tasks_lock:
            if task_id not in self.active_tasks:
                return

            self.active_tasks[task_id].setdefault("logs", []).append(
                {"timestamp": utcnow().isoformat(), "level": level, "message": message}
            )

    def cancel_task(self, task_id: str) -> bool:
        """Mark a task cancelled. Returns False when it is unknown or already finished."""
        with self._tasks_lock:
            if task_id not in self.active_tasks:
                return False
            if self.active_tasks[task_id].get("status") in {"completed", "failed", "cancelled"}:
                return False
            self.active_tasks[task_id]["status"] = "cancelled"
            self.active_tasks[task_id]["message"] = "Task cancelled by user"
            self.active_tasks[task_id]["completed_at"] = utcnow().isoformat()
            return True

    def mark_task_failed(self, task_id: str, error: str) -> None:
        """Record a failure, unless the task already reached a final state."""
        with self._tasks_lock:
            task = self.active_tasks.get(task_id)
            if not task or task.get("status") in {"completed", "cancelled", "failed"}:
                return
            task["status"] = "failed"
            task["error"] = error
            task["failed_at"] = utcnow().isoformat()
        self.add_task_log(task_id, "ERROR", f"GitHub document review failed: {error}")

    def is_task_cancelled(self, task_id: str) -> bool:
        """Whether the task has been cancelled; polled between review stages."""
        with self._tasks_lock:
            return self.active_tasks.get(task_id, {}).get("status") == "cancelled"

    def _cancelled_result(
        self, task_id: str, stats: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        with self._tasks_lock:
            task = self.active_tasks[task_id]
            task["status"] = "cancelled"
            task["message"] = "GitHub document review cancelled"
            task["stats"] = stats or task.get("stats", {})
            task["completed_at"] = utcnow().isoformat()
        self.add_task_log(task_id, "INFO", "GitHub document review cancelled")
        return {
            "success": False,
            "cancelled": True,
            "task_id": task_id,
            "stats": stats or {},
        }
