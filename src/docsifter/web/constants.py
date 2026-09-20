"""Shared constants for the Web layer.

These live apart from the route modules so that the configuration surface --
which keys the Web UI may edit, which ones must never be echoed back -- can be
read in one place instead of being reconstructed from the handlers.
"""

# Keys the generic /config endpoint accepts. Anything outside this set is
# rejected rather than silently ignored, so a typo in the UI surfaces as a 400.
EDITABLE_CONFIG_KEYS = {
    "forced_fixes",
    "skip_file_patterns",
    "skip_text_patterns",
    "whitelist",
}

# Never included in a config response. Secrets reach the process through the
# environment or an explicit config file and are not read back over HTTP.
SENSITIVE_CONFIG_KEYS = {
    "email_password",
    "github_token",
    "llm_api_key",
    "openai_api_key",
}

# Settings the LLM panel may change. The API key is handled separately because
# it must stay in memory; everything else is safe to persist.
LLM_BOOL_KEYS = ("llm_review_enabled", "context_review_enabled", "pr_llm_enabled")
LLM_TEXT_KEYS = ("llm_endpoint", "llm_model")
CONTEXT_SCOPES = ("flagged", "all")
LLM_INT_KEYS = ("llm_max_reviews", "llm_timeout_seconds", "context_max_files")
LLM_INT_BOUNDS = {
    "llm_max_reviews": (1, 1000),
    "llm_timeout_seconds": (1, 600),
    "context_max_files": (1, 10000),
}

# Extensions the directory browser offers as reviewable files. The review
# pipeline itself decides what it can parse; this only shapes the picker.
WEB_SUPPORTED_EXTENSIONS = (
    ".adoc",
    ".asciidoc",
    ".asc",
    ".md",
    ".markdown",
    ".txt",
)
