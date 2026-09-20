#!/usr/bin/env python3
"""Configuration loading and path management for DocSifter."""

import json
import logging
import os
from typing import Any, Dict

from .runtime import get_resource_path, get_runtime_path

logger = logging.getLogger(__name__)

DEFAULT_RULE_DEFINITIONS = {
    # The context noun may sit behind a product name: "登陆到 Grafana 控制台" is
    # the ordinary shape in Chinese technical writing, and requiring the noun to
    # follow 到 directly meant the rule silently missed it. One Latin word is
    # allowed in between; the landing sense (登陆月球, 台风登陆) stays untouched.
    r"登陆(?=(?:到|至)?\s*(?:[A-Za-z][\w.-]*\s+)?(?:账号|账户|帐号|帐户|系统|平台|网站|应用|后台|页面|界面|服务|控制台|客户端|服务器|流程|入口|状态|功能|操作))": {
        "id": "zh.terminology.login",
        "replacement": "登录",
        "severity": "warning",
        "message": "Use '登录' in authentication contexts; preserve literal landing usage.",
    },
    "帐号": {
        "id": "zh.terminology.account",
        "replacement": "账号",
        "severity": "warning",
        "message": "Use the preferred product term '账号'.",
    },
    "帐户": {
        "id": "zh.terminology.user-account",
        "replacement": "账户",
        "severity": "warning",
        "message": "Use the preferred product term '账户'.",
    },
    # A run collapses to one. As the literal string "的的" this replaced pairs
    # left to right, so "的的的" came out as "的的" -- still wrong, and the
    # corpus had recorded that output as the expected result.
    r"的{2,}": {
        "id": "zh.repetition.de",
        "replacement": "的",
        "severity": "error",
        "message": "Remove the duplicated character '的'.",
    },
    "轮循": {
        "id": "zh.spelling.polling",
        "replacement": "轮询",
        "severity": "error",
        "message": "Use the standard spelling '轮询'.",
    },
    "想对重要": {
        "id": "zh.spelling.relatively-important",
        "replacement": "相对重要",
        "severity": "error",
        "message": "Correct the typo to '相对重要'.",
    },
    "参数list": {
        "id": "zh.terminology.parameter-list",
        "replacement": "参数列表",
        "severity": "warning",
        "message": "Use the Chinese term '参数列表' in prose.",
    },
}


class ConfigManager:
    def __init__(self, config_file: str = None):
        self.config_file = config_file or get_runtime_path("config.json")
        # Keys that must never be written to config.json.
        self.environment_override_keys = set()
        # Of those, the ones an environment variable actually pinned. A secret
        # typed into the Web UI is non-persistent but not environment-locked.
        self.env_sourced_keys = set()
        self.config = self.load_config()

    def load_whitelist_from_json(self, json_file: str = None):
        json_file = json_file or get_resource_path("whitelist.json")
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("whitelist", []))
        except FileNotFoundError:
            return set()

    def get_default_config(self) -> Dict[str, Any]:
        return {
            "whitelist": list(self.load_whitelist_from_json()),
            "forced_fixes": {
                pattern: rule["replacement"] for pattern, rule in DEFAULT_RULE_DEFINITIONS.items()
            },
            "rule_metadata": {
                pattern: {key: value for key, value in rule.items() if key != "replacement"}
                for pattern, rule in DEFAULT_RULE_DEFINITIONS.items()
            },
            "skip_text_patterns": [
                r"^\s*'''",
                r"^\s*\+.*",
                r"^\s*====",
                r"^\s*\[\#.*\]",
                r"^\s*\[\[.*\]\]",
                r"^\s*image::.*",
                r"^\s*include::.*",
                r"^\s*//.*",
                r"^\s*(?:\)|\(|\{|\}|\[|\]|\}\)|\(\{|\*)\s*$",
                r"^\s*\[.*\]$",
                r"^argument$",
                r"^<[^<>]+>$",
                r"^\|\[argument\]$",
                r"^\($",
                r"^/$",
                r"^\s*IS\s*$",
                r"^\s*AS\s*$",
                r"^\s*WITH\s*$",
            ],
            "default_model": "shibing624/chinese-text-correction-1.5b",
            "ai_correction_enabled": False,
            "skip_file_patterns": [],
            "model_backend": "local",
            "ollama_base_url": "http://127.0.0.1:11434",
            "openai_base_url": "",
            "openai_api_key": "",
            "llm_review_enabled": False,
            "context_review_enabled": False,
            "llm_endpoint": "",
            "llm_model": "",
            "llm_api_key": "",
            "llm_max_reviews": 20,
            "llm_timeout_seconds": 60,
            # Context review sends a whole document per file, so a directory-wide
            # run needs its own ceiling in addition to llm_max_reviews.
            "context_max_files": 50,
            # "flagged" reviews only files the earlier layers already flagged, so
            # the cost of this layer follows findings like the rest of the
            # pipeline. "all" reviews every file, which is what the layer is for
            # — a clean file can still contradict itself — at a cost that follows
            # document count instead.
            "context_review_scope": "flagged",
            # Webhook reviews run unattended and can fire many times a day, so
            # the optional LLM layers need their own opt-in on that path.
            "pr_llm_enabled": False,
            # Base64 inflates attachments by ~1/3 and most providers reject
            # messages above roughly 10-25 MB.
            # Every configurable email setting is declared here so the key set
            # has one home; they used to exist only as inline defaults at each
            # read site, which is how a settings endpoint came to drop four of
            # them silently.
            "email_smtp_server": "",
            "email_smtp_port": 587,
            "email_username": "",
            "email_password": "",
            "email_use_tls": True,
            "email_sender": "",
            "email_recipients": [],
            "email_subject_template": "DocSifter Review [TASK_ID] completed",
            "email_notifications_enabled": False,
            "email_max_attachment_mb": 10,
            "notify_on_local_complete": True,
            "notify_on_github_complete": True,
            "notify_on_error": True,
            "attach_report": True,
            # Documents above this are skipped. Reviews are serialized, so one
            # oversized file would hold up every later review.
            "max_file_size_mb": 5,
            # Review history, monitor logs, and generated reports past this age
            # are removed at web startup. Set to 0 to keep everything.
            "retention_days": 90,
        }

    def load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, encoding="utf-8") as f:
                    config = json.load(f)
                    if "skip_text_patterns" not in config and "blacklist_patterns" in config:
                        config["skip_text_patterns"] = config.pop("blacklist_patterns")
                    default_config = self.get_default_config()
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return self.apply_environment_overrides(config)
            except Exception as e:
                logger.warning("failed to load config file, using defaults: %s", e)

        return self.apply_environment_overrides(self.get_default_config())

    def apply_environment_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Override sensitive config keys from environment variables."""
        env_mapping = {
            "GITHUB_TOKEN": "github_token",
            "EMAIL_SMTP_SERVER": "email_smtp_server",
            "EMAIL_USERNAME": "email_username",
            "EMAIL_PASSWORD": "email_password",
            "EMAIL_SENDER": "email_sender",
            "LLM_ENDPOINT": "llm_endpoint",
            "LLM_MODEL": "llm_model",
            "LLM_API_KEY": "llm_api_key",
            "MODEL_BACKEND": "model_backend",
            "OLLAMA_BASE_URL": "ollama_base_url",
            "OPENAI_BASE_URL": "openai_base_url",
            "OPENAI_API_KEY": "openai_api_key",
        }

        def get_env(suffix: str) -> str:
            return os.getenv(f"DOCSIFTER_{suffix}", "")

        for suffix, config_key in env_mapping.items():
            value = get_env(suffix)
            if value:
                config[config_key] = value
                self.environment_override_keys.add(config_key)
                self.env_sourced_keys.add(config_key)

        smtp_port = get_env("EMAIL_SMTP_PORT")
        if smtp_port:
            try:
                config["email_smtp_port"] = int(smtp_port)
                self.environment_override_keys.add("email_smtp_port")
                self.env_sourced_keys.add("email_smtp_port")
            except ValueError:
                logger.warning("ignoring invalid DOCSIFTER_EMAIL_SMTP_PORT: %s", smtp_port)

        recipients = get_env("EMAIL_RECIPIENTS")
        if recipients:
            config["email_recipients"] = [
                item.strip() for item in recipients.split(",") if item.strip()
            ]
            self.environment_override_keys.add("email_recipients")
            self.env_sourced_keys.add("email_recipients")

        enabled = get_env("EMAIL_NOTIFICATIONS_ENABLED")
        if enabled:
            config["email_notifications_enabled"] = enabled.lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            self.environment_override_keys.add("email_notifications_enabled")
            self.env_sourced_keys.add("email_notifications_enabled")

        llm_enabled = get_env("LLM_REVIEW_ENABLED")
        if llm_enabled:
            config["llm_review_enabled"] = llm_enabled.lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            self.environment_override_keys.add("llm_review_enabled")
            self.env_sourced_keys.add("llm_review_enabled")

        pr_llm = get_env("PR_LLM_ENABLED")
        if pr_llm:
            config["pr_llm_enabled"] = pr_llm.lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            self.environment_override_keys.add("pr_llm_enabled")
            self.env_sourced_keys.add("pr_llm_enabled")

        context_scope = get_env("CONTEXT_REVIEW_SCOPE").strip().lower()
        if context_scope in {"flagged", "all"}:
            config["context_review_scope"] = context_scope
            self.environment_override_keys.add("context_review_scope")
            self.env_sourced_keys.add("context_review_scope")
        elif context_scope:
            logger.warning("ignoring invalid DOCSIFTER_CONTEXT_REVIEW_SCOPE: %s", context_scope)

        context_enabled = get_env("CONTEXT_REVIEW_ENABLED")
        if context_enabled:
            config["context_review_enabled"] = context_enabled.lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            self.environment_override_keys.add("context_review_enabled")
            self.env_sourced_keys.add("context_review_enabled")

        return config

    def save_config(self):
        try:
            persisted_config = {
                key: value
                for key, value in self.config.items()
                if key not in self.environment_override_keys
            }
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(persisted_config, f, ensure_ascii=False, indent=2)
            os.chmod(self.config_file, 0o600)
        except Exception as e:
            logger.error("failed to save config file: %s", e)

    def get_config(self) -> Dict[str, Any]:
        return self.config

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def update_config(self, key: str, value: Any):
        self.config[key] = value
        self.save_config()

    def update_secret(self, key: str, value: Any):
        """Set a secret for this process only; never write it to config.json.

        ``save_config`` skips every key in ``environment_override_keys``, so
        registering the key there is what keeps it off disk.
        """
        self.config[key] = value
        self.environment_override_keys.add(key)
        self.save_config()

    def is_environment_locked(self, key: str) -> bool:
        """Is this key currently pinned by an environment variable?"""
        return key in self.env_sourced_keys
