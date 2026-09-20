#!/usr/bin/env python3
"""Text correction engine combining rule-based fixes with optional model output."""

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Tuple

import requests

from . import extractors as _extractors
from .runtime import get_resource_path, get_runtime_path

logger = logging.getLogger(__name__)

GptCorrector = None
GPT_AVAILABLE: bool | None = None
DEFAULT_MODEL = "shibing624/chinese-text-correction-1.5b"


class ModelReviewError(RuntimeError):
    """Raised when an explicitly requested model cannot complete a review."""


class ModelUnavailableError(ModelReviewError):
    """Raised when the selected model runtime cannot be initialized."""


class ModelExecutionError(ModelReviewError):
    """Raised when an initialized model fails during correction."""


REMOTE_TIMEOUT_SECONDS = 120

CORRECTION_SYSTEM_PROMPT = (
    "You correct typos and grammar mistakes in Simplified Chinese technical "
    "documentation sentences. Reply with the corrected sentence only, no "
    "explanations. Never modify placeholder tokens such as __URL_0__ or "
    "__WHITELIST_1__."
)


class TransformersBackend:
    """Local small model served through pycorrector's GptCorrector (transformers)."""

    kind = "local"

    def __init__(self, model_name: str):
        if not load_gpt_corrector():
            raise ModelUnavailableError(
                "AI model runtime is unavailable. Install the model extra "
                "before selecting a local model: pip install -r "
                "requirements-model.txt from a checkout, or see the README."
            )

        try:
            logger.info("initializing correction model: %s", model_name)
            self.model_name_or_path = model_name

            try:
                self.client = GptCorrector(model_name_or_path=model_name)
            except ValueError as e:
                if "accelerate" not in str(e):
                    raise

                # Some versions of accelerate conflict with device_map auto-selection.
                logger.warning("accelerate conflict detected, retrying in compatibility mode")
                old_device_map = os.environ.get("TRANSFORMERS_NO_DEVICE_MAP")
                os.environ["TRANSFORMERS_NO_DEVICE_MAP"] = "1"
                try:
                    self.client = GptCorrector(model_name_or_path=model_name)
                finally:
                    if old_device_map is None:
                        os.environ.pop("TRANSFORMERS_NO_DEVICE_MAP", None)
                    else:
                        os.environ["TRANSFORMERS_NO_DEVICE_MAP"] = old_device_map

            logger.info("model ready: %s", model_name)
            self._validate(model_name)
        except ModelUnavailableError:
            raise
        except Exception as e:
            logger.exception("failed to initialize correction model %s", model_name)
            raise ModelUnavailableError(f"Failed to initialize model {model_name}: {e}") from e

    def _validate(self, model_name: str):
        """Feed a known typo and require the model to correct it."""
        try:
            test_result = self.client.correct_batch(["测试文挡"])
            logger.debug("model validation result: %s", test_result)

            if not test_result:
                raise RuntimeError("Model validation returned no result")

            target = (
                test_result[0].get("target", "")
                if isinstance(test_result[0], dict)
                else test_result[0]
            )
            target_clean = re.sub(
                r"<think>.*?</think>", "", target, flags=re.DOTALL | re.IGNORECASE
            ).strip()

            if target_clean != "测试文挡" and "文档" in target_clean:
                logger.info("model validation passed")
            else:
                raise RuntimeError(
                    "Model validation did not correct the expected sample. "
                    "Use a supported transformers version or another correction model."
                )
        except Exception as test_e:
            raise RuntimeError(f"Model validation failed: {test_e}") from test_e

    def correct_batch(self, texts: List[str]) -> List:
        return self.client.correct_batch(texts)


class OllamaBackend:
    """Local model exposed through an Ollama /api/chat endpoint."""

    kind = "ollama"

    def __init__(self, model_name: str, base_url: str = ""):
        self.model_name = model_name
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise ModelUnavailableError(
                "Ollama base URL is not configured. Set ollama_base_url "
                "(default http://127.0.0.1:11434)."
            )

    def correct_batch(self, texts: List[str]) -> List[str]:
        corrected = []
        for text in texts:
            corrected.append(self._chat(text))
        return corrected

    def _chat(self, text: str) -> str:
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": CORRECTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "temperature": 0,
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=REMOTE_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            return str(response.json()["message"]["content"])
        except requests.RequestException as e:
            raise ModelExecutionError(f"Ollama request failed: {e}") from e
        except (KeyError, ValueError) as e:
            raise ModelExecutionError(f"Unexpected Ollama response structure: {e}") from e


class OpenAICompatibleBackend:
    """Remote model exposed through an OpenAI-compatible chat completions API."""

    kind = "openai"

    def __init__(self, model_name: str, base_url: str = "", api_key: str = ""):
        self.model_name = model_name
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        if not self.base_url:
            raise ModelUnavailableError(
                "OpenAI-compatible base URL is not configured. Set openai_base_url, "
                "for example https://api.openai.com/v1."
            )

    def correct_batch(self, texts: List[str]) -> List[str]:
        corrected = []
        for text in texts:
            corrected.append(self._chat(text))
        return corrected

    def _chat(self, text: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": CORRECTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=REMOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])
        except requests.RequestException as e:
            raise ModelExecutionError(f"OpenAI-compatible request failed: {e}") from e
        except (KeyError, IndexError, ValueError) as e:
            raise ModelExecutionError(
                f"Unexpected OpenAI-compatible response structure: {e}"
            ) from e


SUPPORTED_MODEL_BACKENDS = ("local", "ollama", "openai")


def load_gpt_corrector() -> bool:
    """Lazy-load local small-model correction dependencies."""
    global GPT_AVAILABLE, GptCorrector

    if GptCorrector is not None:
        return True
    if GPT_AVAILABLE is False:
        return False

    try:
        from pycorrector.gpt.gpt_corrector import GptCorrector as LoadedGptCorrector

        GptCorrector = LoadedGptCorrector
        GPT_AVAILABLE = True
    except ImportError:
        GPT_AVAILABLE = False
        return False

    try:
        import transformers

        transformers_version = transformers.__version__
        logger.info("detected transformers version: %s", transformers_version)

        major_version = int(transformers_version.split(".")[0])
        minor_version = int(transformers_version.split(".")[1])

        # transformers >=4.50 may return empty corrections with some models
        if major_version > 4 or (major_version == 4 and minor_version >= 50):
            logger.warning(
                "transformers %s may be incompatible with some models; install a "
                "supported version below 4.50 and try again",
                transformers_version,
            )
    except Exception as e:
        logger.warning("could not check transformers version: %s", e)

    return True


class TextCorrector:
    def __init__(self, config_data: Dict, server_mode: bool = False):
        self.whitelist = config_data.get("whitelist", [])
        self.forced_fixes = config_data.get("forced_fixes", {})
        self.rule_metadata = config_data.get("rule_metadata", {})
        self.skip_text_patterns = config_data.get("skip_text_patterns", [])

        self.skip_file_patterns = config_data.get("skip_file_patterns", [])
        self.ai_correction_enabled = bool(config_data.get("ai_correction_enabled", False))
        self.server_mode = server_mode

        # Default to the 1.5B model — most CPU-friendly starting point.
        self.current_model = config_data.get("default_model") or DEFAULT_MODEL

        self.backend_kind = str(config_data.get("model_backend") or "local").strip().lower()
        if self.backend_kind not in SUPPORTED_MODEL_BACKENDS:
            raise ValueError(
                f"Unsupported model backend: {self.backend_kind!r}. "
                f"Supported backends: {', '.join(SUPPORTED_MODEL_BACKENDS)}."
            )
        self.ollama_base_url = str(config_data.get("ollama_base_url") or "http://127.0.0.1:11434")
        self.openai_base_url = str(config_data.get("openai_base_url") or "")
        self.openai_api_key = str(config_data.get("openai_api_key") or "")

        self.compiled_skip_text_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.skip_text_patterns
        ]
        self.compiled_skip_patterns = [re.compile(pattern) for pattern in self.skip_file_patterns]

        self.gpt_client = None
        self.model_init_failed = False
        self.model_error = None
        # In server mode defer model loading to first actual use.
        if self.ai_correction_enabled and not server_mode:
            self.init_corrector()

    def _build_backend(self, model_name: str):
        """Instantiate the correction backend for the configured kind."""
        if self.backend_kind == "local":
            return TransformersBackend(model_name)
        if self.backend_kind == "ollama":
            return OllamaBackend(model_name, base_url=self.ollama_base_url)
        return OpenAICompatibleBackend(
            model_name, base_url=self.openai_base_url, api_key=self.openai_api_key
        )

    def init_corrector(self, model_name: str = None) -> bool:
        if not self.ai_correction_enabled:
            return False

        try:
            selected_model = model_name or self.current_model
            self.current_model = selected_model
            logger.info("initializing correction backend: %s", self.backend_kind)
            self.gpt_client = self._build_backend(selected_model)

            self.model_error = None
            self.model_init_failed = False
            return True

        except Exception as e:
            logger.exception("failed to initialize correction model")
            self.gpt_client = None
            self.model_init_failed = True
            self.model_error = f"Failed to initialize model {model_name or self.current_model}: {e}"
            return False

    def update_model(self, model_name: str):
        self.ai_correction_enabled = True
        self.model_init_failed = False
        self.model_error = None
        logger.info("switching model to: %s", model_name)

        self.release_model()
        self.current_model = model_name
        # Re-initialize even in server mode to make the new model available.
        if not self.init_corrector(model_name):
            raise ModelUnavailableError(
                self.model_error or f"Failed to initialize model: {model_name}"
            )

    def use_rule_based_mode(self):
        """Disable local model correction and use rule preview checks only."""
        self.ai_correction_enabled = False
        self.model_init_failed = False
        self.model_error = None
        self.release_model()

    def release_model(self):
        if self.gpt_client is not None:
            try:
                if hasattr(self.gpt_client, "model") and self.gpt_client.model is not None:
                    self.gpt_client.model.cpu()
                    del self.gpt_client.model
                    self.gpt_client.model = None

                if hasattr(self.gpt_client, "tokenizer") and self.gpt_client.tokenizer is not None:
                    del self.gpt_client.tokenizer
                    self.gpt_client.tokenizer = None

                del self.gpt_client
                self.gpt_client = None

                import gc

                gc.collect()

                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                        logger.debug("GPU memory released")
                except ImportError:
                    pass

                logger.debug("model resources released")

            except Exception as e:
                logger.warning("problem during model release: %s", e)

    def __del__(self):
        try:
            self.release_model()
        except Exception:
            pass

    def should_skip_file(self, file_path: str) -> bool:
        for pattern in self.compiled_skip_patterns:
            if pattern.search(file_path):
                return True
        return False

    def should_skip_text(self, text: str) -> bool:
        for pattern in self.compiled_skip_text_patterns:
            if pattern.search(text):
                return True
        return False

    def has_meaningful_text(self, text: str) -> bool:
        return _extractors.has_meaningful_text(text)

    def extract_line_comments(self, line: str, lang: str = "generic") -> List[str]:
        return _extractors.extract_line_comments(line, lang=lang)

    def extract_text_from_file(self, file_path: str, content: str) -> List[Tuple[int, str, str]]:
        """Return a list of (line_number, original_line, plain_text) tuples to review."""
        file_extension = os.path.splitext(file_path)[1].lower()
        extractor = _extractors.get_text_extractor(file_extension)
        if extractor is None:
            logger.warning("unsupported file type: %s", file_extension)
            return []
        return extractor(content)

    def _extract_text_from_asciidoc(self, content: str) -> List[Tuple[int, str, str]]:
        return _extractors.extract_asciidoc_text(content)

    def _extract_text_from_markdown(self, content: str) -> List[Tuple[int, str, str]]:
        return _extractors.extract_markdown_text(content)

    def protect_whitelist_words(self, text: str) -> Tuple[str, Dict[str, str]]:
        replacements = {}
        protected_text = text

        for i, word in enumerate(self.whitelist):
            if word in protected_text:
                placeholder = f"__WHITELIST_{i}__"
                replacements[placeholder] = word
                protected_text = protected_text.replace(word, placeholder)

        return protected_text, replacements

    def restore_whitelist_words(self, text: str, replacements: Dict[str, str]) -> str:
        result = text

        # Restore in reverse order to avoid nested-replacement issues.
        sorted_items = sorted(replacements.items(), key=lambda x: x[0], reverse=True)

        for placeholder, original in sorted_items:
            result = result.replace(placeholder, original)

        remaining_placeholders = re.findall(r"__WHITELIST_\d+__", result)
        if remaining_placeholders:
            logger.warning("unrestored whitelist placeholders: %s", remaining_placeholders)
            for placeholder in remaining_placeholders:
                match = re.search(r"__WHITELIST_(\d+)__", placeholder)
                if match:
                    index = int(match.group(1))
                    if index < len(self.whitelist):
                        result = result.replace(placeholder, self.whitelist[index])
                    else:
                        result = result.replace(placeholder, "")

        return result

    def protect_asciidoc_syntax(self, text: str) -> Tuple[str, Dict[str, str]]:
        patterns = [
            (r"!?\[[^\]]*\]\([^\)]+\)", "MDLINK"),
            (r"https?://[^\s)\]>]+", "URL"),
            (r"`[^`]+`", "CODE"),
            (r"\*\*([^*]+)\*\*", "BOLD"),
            (r"\*([^*]+)\*", "ITALIC"),
            (r"\[([^\]]+)\]", "LINK"),
            (r"<<[^>]+>>", "XREF"),
            (r"\{[^}]+\}", "ATTR"),
        ]

        replacements = {}
        combined_pattern = re.compile(
            "|".join(f"(?P<{prefix}>{pattern})" for pattern, prefix in patterns)
        )

        def replace_match(match):
            prefix = match.lastgroup or "TECH"
            placeholder = f"__{prefix}_{len(replacements)}__"
            replacements[placeholder] = match.group(0)
            return placeholder

        protected_text = combined_pattern.sub(replace_match, text)

        return protected_text, replacements

    def restore_protected_regions(self, text: str, replacements: Dict[str, str]) -> str:
        result = text

        sorted_items = sorted(replacements.items(), key=lambda x: x[0], reverse=True)

        for placeholder, original in sorted_items:
            # Exact matches only. Guessing at a damaged placeholder used to fall
            # back to its bare index, so a single "0" anywhere in the sentence
            # was replaced with the whole protected span, turning "30 秒" into
            # "3`retry_limit` 秒". Callers detect a missing placeholder instead.
            result = result.replace(placeholder, original)

        return result

    def placeholders_intact(self, before: str, after: str, replacements: Dict[str, str]) -> bool:
        """Did a rewrite leave every protected placeholder untouched?"""
        return all(
            after.count(placeholder) == before.count(placeholder) for placeholder in replacements
        )

    def restore_safe_model_output(
        self,
        protected_input: str,
        model_output: str,
        syntax_replacements: Dict[str, str],
        whitelist_replacements: Dict[str, str],
    ) -> str | None:
        replacements = {**syntax_replacements, **whitelist_replacements}
        for placeholder in replacements:
            if model_output.count(placeholder) != protected_input.count(placeholder):
                logger.warning("discarding model output that changed a protected region")
                return None

        input_length = len(protected_input.strip())
        output_length = len(model_output.strip())
        output_too_short = input_length and output_length < input_length * 0.5
        output_too_long = input_length and output_length > max(input_length * 3, input_length + 100)
        if output_too_short or output_too_long:
            logger.warning("discarding model output with an unsafe length change")
            return None

        restored = self.restore_whitelist_words(model_output, whitelist_replacements)
        restored = self.restore_protected_regions(restored, syntax_replacements)
        if re.search(r"__(?:WHITELIST|\w+)_\d+__", restored):
            logger.warning("discarding model output with unresolved placeholders")
            return None
        return restored

    def is_balanced_brackets(self, text: str) -> bool:
        stack = []
        pairs = {"(": ")", "[": "]", "{": "}", "（": "）", "【": "】"}

        for char in text:
            if char in pairs:
                stack.append(pairs[char])
            elif char in pairs.values():
                if not stack or stack.pop() != char:
                    return False

        return len(stack) == 0

    def should_protect_text(self, text: str) -> bool:
        """Return True if the text is dense with technical tokens that the model should not touch.

        A bare all-caps acronym is deliberately not one of these patterns. In
        Chinese technical writing a sentence naming API or SQL is prose, and
        because Chinese has no spaces the word count is tiny, so one acronym was
        enough to clear the density threshold. That suppressed a fifth of the
        lines in this project's own documentation while protecting nothing the
        model would have damaged. The remaining patterns mark content that is
        machine-readable rather than prose.
        """
        tech_patterns = [
            r"\b\w+\.[a-z]{2,3}\b",
            r"\b\d+\.\d+\b",
            r"[a-zA-Z]+://[^\s]+",
            r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
        ]

        tech_count = sum(len(re.findall(pattern, text)) for pattern in tech_patterns)
        word_count = len(text.split())

        if word_count > 0 and tech_count / word_count > 0.3:
            return True

        if not self.is_balanced_brackets(text):
            return True

        return False

    def _filter_model_artifacts(self, text: str) -> str:
        """Strip <think> / <thinking> tags produced by reasoning-capable models."""
        if not text:
            return text

        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def call_gpt_corrector(self, text: str, debug: bool = False) -> str | None:
        if not self.ai_correction_enabled:
            if debug:
                logger.debug("AI correction disabled, skipping")
            return None

        if self.model_init_failed:
            if debug:
                logger.debug("model init previously failed, skipping")
            return None

        if not self.gpt_client:
            if debug:
                logger.debug("first use, initializing model: %s", self.current_model)
            if not self.init_corrector(self.current_model) or not self.gpt_client:
                raise ModelUnavailableError(
                    self.model_error or f"Failed to initialize model: {self.current_model}"
                )

        if self.should_protect_text(text):
            if debug:
                logger.debug("text contains technical tokens, skipping model correction")
            return None

        return self._run_model_correction(text, debug)

    def _run_model_correction(self, text: str, debug: bool = False) -> str | None:
        """Run one protected model correction round through the active backend."""
        protected_text, syntax_replacements = self.protect_asciidoc_syntax(text)
        protected_text, whitelist_replacements = self.protect_whitelist_words(protected_text)

        if debug:
            logger.debug("protected text: %s...", protected_text[:100])
            logger.debug(
                "syntax replacements: %s, whitelist replacements: %s",
                len(syntax_replacements),
                len(whitelist_replacements),
            )
            logger.debug("calling %s backend: %s", self.backend_kind, self.current_model)

        try:
            batch_res = self.gpt_client.correct_batch([protected_text])
            if debug:
                logger.debug("raw result: %s", batch_res)

            if not batch_res:
                if debug:
                    logger.debug("model returned empty result")
                raise ModelExecutionError("Model returned an empty correction result")

            result_item = batch_res[0]
            corrected_text = (
                result_item.get("target", "") if isinstance(result_item, dict) else str(result_item)
            )

            corrected_text = self._filter_model_artifacts(corrected_text)
            if debug:
                logger.debug("correction: %s...", corrected_text[:100])

            corrected_text = self.restore_safe_model_output(
                protected_text,
                corrected_text,
                syntax_replacements,
                whitelist_replacements,
            )
            if corrected_text is None:
                return None

            if not corrected_text:
                if debug:
                    logger.debug("corrected text is empty")
                raise ModelExecutionError("Model returned empty corrected text")

            cleaned_original = text.strip()
            cleaned_corrected = corrected_text.strip()
            if cleaned_corrected == cleaned_original:
                if debug:
                    logger.debug("no change after correction")
                return None

            if debug:
                logger.debug("final result: %s...", corrected_text[:100])
            return corrected_text

        except ModelExecutionError:
            raise
        except Exception as e:
            # The traceback matters while diagnosing a backend; otherwise the
            # message is enough, and the raised error carries the detail on.
            if debug:
                logger.exception("correction model call failed")
            else:
                logger.warning("correction model call failed: %s", e)
            raise ModelExecutionError(f"Model correction failed: {e}") from e

    def apply_forced_fixes_with_metadata(self, text: str) -> Tuple[str, List[Dict]]:
        result = text
        matches = []
        metadata = getattr(self, "rule_metadata", {})
        for pattern, replacement in self.forced_fixes.items():
            try:
                if re.search(pattern, result):
                    rule = metadata.get(pattern, {})
                    matches.append(
                        {
                            "id": rule.get("id", f"custom.{pattern}"),
                            "message": rule.get(
                                "message", f"Use '{replacement}' instead of '{pattern}'."
                            ),
                            "severity": rule.get("severity", "warning"),
                        }
                    )
                result = re.sub(pattern, replacement, result)
            except re.error as e:
                logger.warning("invalid forced-fix pattern %r: %s", pattern, e)
        return result, matches

    def correct_text_with_metadata(self, text: str, debug: bool = False) -> Tuple[str | None, Dict]:
        if self.should_skip_text(text):
            return None, {"review_source": "none", "severity": "suggestion", "rule_ids": []}

        protected_text, syntax_replacements = self.protect_asciidoc_syntax(text)
        protected_text, whitelist_replacements = self.protect_whitelist_words(protected_text)
        forced_protected, matched_rules = self.apply_forced_fixes_with_metadata(protected_text)

        # A forced-fix pattern can match inside a placeholder (a rule normalizing
        # underscores will), which corrupts the protected span it stands for. The
        # model path already discards output in that case; the rule path must too,
        # rather than restoring a damaged placeholder into the document.
        all_replacements = {**syntax_replacements, **whitelist_replacements}
        if not self.placeholders_intact(protected_text, forced_protected, all_replacements):
            logger.warning(
                "discarding forced fixes that damaged a protected region; "
                "check the forced-fix rules for a pattern matching placeholder text"
            )
            forced_protected = protected_text
            matched_rules = []

        forced_corrected = self.restore_whitelist_words(forced_protected, whitelist_replacements)
        forced_corrected = self.restore_protected_regions(forced_corrected, syntax_replacements)

        if debug and matched_rules:
            logger.debug("applied rules: %s", [rule["id"] for rule in matched_rules])

        severity_order = {"suggestion": 0, "warning": 1, "error": 2}
        severity = max(
            (rule["severity"] for rule in matched_rules),
            key=lambda value: severity_order.get(value, 1),
            default="suggestion",
        )

        model_corrected = self.call_gpt_corrector(forced_corrected, debug=debug)
        if model_corrected and model_corrected != forced_corrected:
            return model_corrected, {
                "review_source": "rule+model" if matched_rules else "model",
                "severity": severity,
                "rule_ids": [rule["id"] for rule in matched_rules],
            }

        if forced_corrected != text:
            return forced_corrected, {
                "review_source": "rule",
                "severity": severity,
                "rule_ids": [rule["id"] for rule in matched_rules],
            }

        return None, {"review_source": "none", "severity": "suggestion", "rule_ids": []}

    def correct_text(self, text: str, debug: bool = False) -> str | None:
        if debug:
            logger.debug("correcting: %s...", text[:100])

        corrected, _ = self.correct_text_with_metadata(text, debug=debug)
        return corrected

    def process_file(self, file_path: str, content: str, debug: bool = False) -> List[Dict]:
        if self.should_skip_file(file_path):
            return []

        if debug:
            logger.debug("processing file: %s", file_path)

        extracted_texts = self.extract_text_from_file(file_path, content)
        changes = []

        if not extracted_texts:
            if debug:
                logger.debug("no text extracted from file")
            return changes

        if debug:
            logger.debug("starting correction for %s text segment(s)", len(extracted_texts))

        for line_num, original_line, extracted_text in extracted_texts:
            if debug:
                logger.debug("correcting line %s: %s...", line_num, extracted_text[:50])

            corrected_text, finding_metadata = self.correct_text_with_metadata(
                extracted_text, debug=debug
            )

            if corrected_text:
                changes.append(
                    {
                        "file_path": file_path,
                        "line_number": line_num,
                        "original_line": original_line,
                        "original_text": extracted_text,
                        "corrected_text": corrected_text,
                        "source": "code" if "// " in original_line else "text",
                        **finding_metadata,
                    }
                )
                if debug:
                    logger.debug("correction: %s -> %s", extracted_text, corrected_text)
            elif debug:
                logger.debug("no correction needed")

        if debug:
            logger.debug("done: %s correction(s) found", len(changes))

        return changes


class FalsePositiveManager:
    def __init__(self, false_positive_file: str = None):
        self.false_positive_file = false_positive_file or get_runtime_path("false_positives.json")
        self.false_positives = self.load_false_positives()

    def load_false_positives(self) -> List[Dict]:
        source_file = self.false_positive_file
        if not os.path.exists(source_file):
            source_file = get_resource_path("false_positives.json")

        if os.path.exists(source_file):
            try:
                with open(source_file, encoding="utf-8") as f:
                    data = json.load(f)

                # Migrate from the old dict-based format if needed.
                if isinstance(data, dict) and "exact_matches" in data:
                    false_positives = []
                    for match in data.get("exact_matches", []):
                        false_positives.append(
                            {
                                "original": match["original"],
                                "corrected": match["corrected"],
                                "is_pattern": False,
                            }
                        )
                    for pattern in data.get("patterns", []):
                        false_positives.append(
                            {"original": pattern, "corrected": "", "is_pattern": True}
                        )
                    return false_positives

                elif isinstance(data, list):
                    return data

            except Exception as e:
                logger.warning("failed to load false positives: %s", e)
        return []

    def save_false_positives(self):
        try:
            with open(self.false_positive_file, "w", encoding="utf-8") as f:
                json.dump(self.false_positives, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("failed to save false positives: %s", e)

    def add_false_positive(
        self,
        original: str,
        corrected: str,
        is_pattern: bool = False,
        note: str = "",
    ):
        false_positive = {
            "original": original,
            "corrected": corrected,
            "is_pattern": is_pattern,
            "note": note,
            "timestamp": str(datetime.now()),
        }
        self.false_positives.append(false_positive)
        self.save_false_positives()

    def is_false_positive(self, original: str, corrected: str) -> bool:
        for fp in self.false_positives:
            if fp["is_pattern"]:
                try:
                    pattern = fp["original"]

                    # Skip patterns that are clearly full sentences — likely mis-added.
                    if len(pattern) > 100:
                        continue

                    if any(char in pattern for char in ["|", "：", "、", "。"]):
                        continue

                    if re.fullmatch(pattern, original):
                        return True
                except re.error:
                    continue
            else:
                if fp["original"] == original and fp["corrected"] == corrected:
                    return True
        return False
