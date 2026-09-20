#!/usr/bin/env python3
"""Optional LLM second-pass review that validates small-model findings.

The reviewer sends questionable findings to an OpenAI-compatible chat
completions endpoint and records a verdict (confirmed/rejected) with a
confidence score on each finding. It is disabled by default; enabling it
sends the surrounding text snippets to the configured endpoint.
"""

import json
import logging
import re
from typing import Any, Dict, List, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_MAX_REVIEWS = 20
DEFAULT_TIMEOUT_SECONDS = 60

# Sources produced by the local small model carry hallucination risk and are
# worth a second opinion; deterministic rule fixes are trusted as-is.
MODEL_SOURCES = {"model", "rule+model"}

SYSTEM_PROMPT = (
    "You are a senior reviewer for Simplified Chinese technical documentation. "
    "You will receive one original sentence and one suggested correction. "
    "Judge whether the correction is necessary and correct. Reply with a single "
    'JSON object only: {"verdict": "confirmed" or "rejected", '
    '"confidence": <number between 0 and 1>, "reason": "<short explanation>"}. '
    "Reject the correction when it changes meaning, breaks terminology, or the "
    "original was already correct."
)

CONTEXT_SYSTEM_PROMPT = (
    "You are a senior reviewer for Simplified Chinese technical documentation. "
    "You will receive numbered lines from one document. Find only cross-line "
    "problems: inconsistent terminology across lines, contradictory statements, "
    "or broken cross-references. Do NOT report spelling or single-line grammar "
    "issues; other passes already handle those. Reply with a JSON array only, "
    'for example [{"lines": [3, 17], "type": "inconsistency", "issue": "...", '
    '"suggestion": "..."}]. Reply with [] when nothing is found.'
)

DEFAULT_MAX_CONTEXT_ISSUES = 10
CONTEXT_MAX_LINES = 200


class LLMReviewError(RuntimeError):
    """Raised when the configured LLM endpoint cannot complete a review."""


class LLMReviewer:
    """Reviews individual findings against an OpenAI-compatible endpoint."""

    def __init__(self, config: Dict[str, Any]):
        self.endpoint = str(config.get("endpoint") or "").rstrip("/")
        self.model = str(config.get("model") or "")
        self.api_key = str(config.get("api_key") or "")
        self.max_reviews = int(config.get("max_reviews") or DEFAULT_MAX_REVIEWS)
        self.timeout = int(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        self.last_context_lines_sent = 0
        self.last_context_lines_dropped = 0

        if not self.endpoint:
            raise LLMReviewError("LLM review endpoint is not configured")
        if not self.model:
            raise LLMReviewError("LLM review model is not configured")

    def should_review(self, change: Dict[str, Any]) -> bool:
        """Return True for findings whose source makes them worth re-checking."""
        if change.get("is_whitespace"):
            return False
        return change.get("review_source") in MODEL_SOURCES

    def select_findings(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        for file_result in results:
            for change in file_result.get("changes", []):
                if len(selected) >= self.max_reviews:
                    break
                if self.should_review(change):
                    selected.append(change)
            if len(selected) >= self.max_reviews:
                break
        return selected

    def _mark_over_budget(
        self, results: List[Dict[str, Any]], selected: List[Dict[str, Any]]
    ) -> int:
        """Label eligible findings that the per-run budget could not cover.

        Without this an unverified finding renders exactly like a rule finding
        that was deliberately trusted, so the report would overstate how much
        the LLM actually checked.
        """
        chosen = {id(change) for change in selected}
        skipped = 0
        for file_result in results:
            for change in file_result.get("changes", []):
                if not self.should_review(change) or id(change) in chosen:
                    continue
                change["llm_verdict"] = {
                    "verdict": "skipped",
                    "confidence": 0.0,
                    "reason": (
                        f"Not verified: the per-run budget of {self.max_reviews} "
                        "finding(s) was already used."
                    ),
                }
                skipped += 1
        return skipped

    def _build_messages(self, change: Dict[str, Any]) -> List[Dict[str, str]]:
        user_content = (
            f"Original sentence:\n{change.get('original_text', '')}\n\n"
            f"Suggested correction:\n{change.get('corrected_text', '')}"
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _chat(self, messages: List[Dict[str, str]]) -> str:
        """Send one chat completion request and return the reply content."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }

        try:
            response = requests.post(
                f"{self.endpoint}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            raise LLMReviewError(f"LLM endpoint request failed: {e}") from e

        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise LLMReviewError(f"Unexpected LLM response structure: {e}") from e

    def _request_verdict(self, change: Dict[str, Any]) -> Dict[str, Any]:
        return self._parse_verdict(self._chat(self._build_messages(change)))

    def _parse_verdict(self, content: str) -> Dict[str, Any]:
        """Parse the verdict JSON, tolerating prose around the object."""
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise LLMReviewError("LLM reply contains no JSON object")

        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise LLMReviewError(f"Invalid JSON in LLM reply: {e}") from e

        verdict = str(parsed.get("verdict", "")).lower()
        if verdict not in ("confirmed", "rejected"):
            raise LLMReviewError(f"Unknown LLM verdict: {verdict!r}")

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)

        return {
            "verdict": verdict,
            "confidence": round(confidence, 2),
            "reason": str(parsed.get("reason", ""))[:500],
        }

    def apply(self, results: List[Dict[str, Any]], debug: bool = False) -> Dict[str, int]:
        """Review eligible findings in place and return summary counters."""
        summary = {"reviewed": 0, "confirmed": 0, "rejected": 0, "errors": 0, "skipped": 0}
        selected = self.select_findings(results)
        summary["skipped"] = self._mark_over_budget(results, selected)

        if summary["skipped"]:
            logger.warning(
                "LLM review budget is %s finding(s) per run; %s eligible finding(s) "
                "were left unverified. Raise llm_max_reviews to cover them.",
                self.max_reviews,
                summary["skipped"],
            )

        if not selected:
            return summary

        logger.info("LLM review: checking %s finding(s) via %s", len(selected), self.model)

        for change in selected:
            try:
                verdict = self._request_verdict(change)
            except LLMReviewError as e:
                summary["errors"] += 1
                # Label it too: an unlabelled eligible finding is indistinguishable
                # from one that was trusted and never sent.
                change["llm_verdict"] = {
                    "verdict": "error",
                    "confidence": 0.0,
                    "reason": f"Not verified: {e}"[:500],
                }
                logger.warning("LLM review error (continuing): %s", e)
                continue

            change["llm_verdict"] = verdict
            summary["reviewed"] += 1
            summary[verdict["verdict"]] += 1
            if debug:
                logger.debug(
                    "[%s] conf=%s %s :: %s",
                    verdict["verdict"],
                    verdict["confidence"],
                    verdict["reason"],
                    str(change.get("original_text", ""))[:40],
                )

        return summary

    def review_context(self, lines: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
        """Find cross-line issues in one document given its numbered lines.

        Only the first ``CONTEXT_MAX_LINES`` extracted lines fit in one request;
        callers are told how much was dropped so a long document is not silently
        reported as fully reviewed.
        """
        if not lines:
            return []

        self.last_context_lines_sent = min(len(lines), CONTEXT_MAX_LINES)
        self.last_context_lines_dropped = max(0, len(lines) - CONTEXT_MAX_LINES)
        numbered = "\n".join(f"{line_no}: {text}" for line_no, text in lines[:CONTEXT_MAX_LINES])
        messages = [
            {"role": "system", "content": CONTEXT_SYSTEM_PROMPT},
            {"role": "user", "content": numbered},
        ]
        return self._parse_context_issues(self._chat(messages))

    def _parse_context_issues(self, content: str) -> List[Dict[str, Any]]:
        """Parse the issues JSON array, tolerating prose and malformed entries."""
        match = re.search(r"\[.*\]", content, flags=re.DOTALL)
        if not match:
            raise LLMReviewError("LLM reply contains no JSON array")

        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise LLMReviewError(f"Invalid JSON in LLM reply: {e}") from e

        issues = []
        for entry in parsed[:DEFAULT_MAX_CONTEXT_ISSUES]:
            if not isinstance(entry, dict):
                continue
            refs = sorted({int(n) for n in entry.get("lines", []) if isinstance(n, (int, float))})
            issue_text = str(entry.get("issue", "")).strip()
            if not refs or not issue_text:
                continue
            issues.append(
                {
                    "refs": refs,
                    "context_type": str(entry.get("type", "inconsistency"))[:40],
                    "issue": issue_text[:500],
                    "suggestion": str(entry.get("suggestion", "")).strip()[:500],
                }
            )
        return issues


def review_context_as_changes(
    reviewer: "LLMReviewer | None",
    file_path: str,
    numbered_lines: List[Tuple[int, str]],
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """Run one cross-line review and shape the issues as report findings.

    Shared by the local and GitHub review paths so both render context findings
    identically. Returns an empty list when the layer is off, the file has no
    reviewable prose, or the endpoint fails for this file.
    """
    if reviewer is None or not numbered_lines:
        return []

    try:
        issues = reviewer.review_context(numbered_lines)
    except Exception as e:
        logger.warning("context review skipped for %s: %s", file_path, e)
        return []

    dropped = getattr(reviewer, "last_context_lines_dropped", 0)
    if dropped:
        logger.warning(
            "context review truncated for %s: reviewed the first %s extracted "
            "line(s), %s later line(s) were not sent",
            file_path,
            reviewer.last_context_lines_sent,
            dropped,
        )

    changes: List[Dict[str, Any]] = []
    for issue in issues:
        first_ref = issue["refs"][0]
        line_text = next((text for no, text in numbered_lines if no == first_ref), "")
        changes.append(
            {
                "line_number": first_ref,
                "original_text": line_text,
                "corrected_text": issue["suggestion"] or issue["issue"],
                "review_source": "context",
                "severity": "suggestion",
                "rule_ids": ["context"],
                "is_whitespace": False,
                "context_type": issue["context_type"],
                "context_refs": issue["refs"],
                "context_issue": issue["issue"],
            }
        )
        if debug:
            logger.debug(
                "[context:%s] lines %s: %s",
                issue["context_type"],
                issue["refs"],
                issue["issue"],
            )
    return changes


def load_llm_reviewer(config_manager: Any) -> LLMReviewer | None:
    """Build an LLMReviewer from persisted configuration, or None if disabled."""
    config = config_manager.config if hasattr(config_manager, "config") else {}
    if not config.get("llm_review_enabled"):
        return None

    llm_config = {
        "endpoint": config.get("llm_endpoint"),
        "model": config.get("llm_model"),
        "api_key": config.get("llm_api_key"),
        "max_reviews": config.get("llm_max_reviews"),
        "timeout_seconds": config.get("llm_timeout_seconds"),
    }
    try:
        return LLMReviewer(llm_config)
    except LLMReviewError as e:
        logger.warning("LLM review disabled: %s", e)
        return None


def load_context_reviewer(config_manager: Any) -> LLMReviewer | None:
    """Build an LLMReviewer for cross-line analysis, or None if disabled."""
    config = config_manager.config if hasattr(config_manager, "config") else {}
    if not config.get("context_review_enabled"):
        return None

    llm_config = {
        "endpoint": config.get("llm_endpoint"),
        "model": config.get("llm_model"),
        "api_key": config.get("llm_api_key"),
        "timeout_seconds": config.get("llm_timeout_seconds"),
    }
    try:
        return LLMReviewer(llm_config)
    except LLMReviewError as e:
        logger.warning("context review disabled: %s", e)
        return None
