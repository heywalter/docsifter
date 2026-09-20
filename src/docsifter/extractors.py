"""Pluggable text extraction for reviewable document formats.

Built-in extractors cover AsciiDoc-family and Markdown files. New formats
(e.g. reStructuredText, docx) plug in without touching the correction engine:

    from docsifter.extractors import register_text_extractor

    def extract_rst(content: str):
        ...  # return (line_number, original_line, plain_text) tuples

    register_text_extractor([".rst"], extract_rst)

An extractor receives the raw file content and returns a list of
``(line_number, original_line, plain_text)`` tuples; lines whose plain text
is empty or noise are simply omitted.
"""

import logging
import re
from typing import Callable, Dict, List, Tuple

ExtractedLine = Tuple[int, str, str]
TextExtractor = Callable[[str], List[ExtractedLine]]

TEXT_EXTRACTORS: Dict[str, TextExtractor] = {}


def register_text_extractor(extensions, extractor: TextExtractor) -> None:
    """Register (or deliberately override) the extractor for file extensions."""
    for extension in extensions:
        TEXT_EXTRACTORS[extension.lower()] = extractor


def get_text_extractor(extension: str) -> TextExtractor | None:
    """Return the extractor registered for ``extension``, if any."""
    return TEXT_EXTRACTORS.get(extension.lower())


def supported_extensions() -> Tuple[str, ...]:
    """Return all extensions that currently have a registered extractor."""
    return tuple(sorted(TEXT_EXTRACTORS))


# Inline code spans must survive markup stripping: the underscore in
# `retry_limit` is part of an identifier, not an emphasis marker. Masking them
# first keeps `sync_config.yaml` from being reported as `syncconfig.yaml`.
INLINE_CODE_SPAN = re.compile(r"(?P<fence>`+)(?P<body>.+?)(?P=fence)")
_MASK_PREFIX = "\x00c"
_MASK_SUFFIX = "\x00"


def mask_inline_code(text: str) -> Tuple[str, List[str]]:
    """Replace inline code spans with placeholders that carry no markup."""
    spans: List[str] = []

    def stash(match: re.Match) -> str:
        spans.append(match.group(0))
        return f"{_MASK_PREFIX}{len(spans) - 1}{_MASK_SUFFIX}"

    return INLINE_CODE_SPAN.sub(stash, text), spans


def restore_inline_code(text: str, spans: List[str]) -> str:
    """Put the original inline code spans back, verbatim."""
    for index, span in enumerate(spans):
        text = text.replace(f"{_MASK_PREFIX}{index}{_MASK_SUFFIX}", span)
    return text


def has_meaningful_text(text: str) -> bool:
    """Heuristic: does this fragment carry reviewable CJK/Latin content?"""
    if len(text) < 3:
        return False
    return bool(re.search(r"[一-龥a-zA-Z]{2,}", text))


def extract_line_comments(line: str, lang: str = "generic") -> List[str]:
    """Pull human-written comments out of a code line, per language."""
    comment_patterns = {
        "sql": r"(--\s*.+?)(?=\n|$)",
        "plsql": r"(--\s*.+?)(?=\n|$)",
        "python": r"(#\s*.+?)(?=\n|$)",
        "java": r"(//\s*.+?)(?=\n|$)",
        "javascript": r"(//\s*.+?)(?=\n|$)",
        "typescript": r"(//\s*.+?)(?=\n|$)",
        "html": r"(<!--\s*.+?-->|//\s*.+?)(?=\n|$)",
        "css": r"(/\*\s*.+?\*/|//\s*.+?)(?=\n|$)",
        "generic": r"(//|#|--)\s*.+",
    }

    if not line.strip():
        return []

    pattern = comment_patterns.get(lang.lower(), comment_patterns["generic"])
    matches = re.findall(pattern, line)

    valid_comments = []
    for comment in matches:
        clean_comment = re.sub(r"^\s*(--|#|//|/\*|<!--)\s*", "", comment.strip())
        clean_comment = re.sub(r"\s*\*/\s*$", "", clean_comment)
        if has_meaningful_text(clean_comment):
            valid_comments.append(clean_comment)

    return valid_comments


def extract_asciidoc_text(content: str) -> List[ExtractedLine]:
    """Extract reviewable prose lines from an AsciiDoc document."""
    lines = content.split("\n")
    extracted_texts: List[ExtractedLine] = []
    in_code_block = False
    code_block_delimiter = None
    fence_length = 0

    for i, line in enumerate(lines):
        original_line_number = i + 1
        stripped_line = line.strip()

        markdown_fence = re.match(r"^(`{3,}|~{3,})(.*)$", stripped_line)
        if not in_code_block:
            if stripped_line in {"----", "....", "===="}:
                in_code_block = True
                code_block_delimiter = stripped_line
                continue
            if markdown_fence:
                marker, _ = markdown_fence.groups()
                in_code_block = True
                code_block_delimiter = marker[0]
                fence_length = len(marker)
                continue
        else:
            if stripped_line == code_block_delimiter:
                in_code_block = False
                code_block_delimiter = None
                continue
            if markdown_fence and code_block_delimiter in {"`", "~"}:
                marker, suffix = markdown_fence.groups()
                if (
                    marker[0] == code_block_delimiter
                    and len(marker) >= fence_length
                    and not suffix.strip()
                ):
                    in_code_block = False
                    code_block_delimiter = None
                    fence_length = 0
                continue
            continue

        comments = extract_line_comments(line)
        for comment in comments:
            if has_meaningful_text(comment):
                extracted_texts.append((original_line_number, comment, comment))

        masked_line, code_spans = mask_inline_code(line)

        # Strip inline comments, but keep URLs like https:// intact.
        text_without_comments = re.sub(r"(?<!:)//.*", "", masked_line)
        text_without_comments = re.sub(r"(#|--|<!--).*", "", text_without_comments).strip()
        text_without_comments = re.sub(r"/\*.*\*/", "", text_without_comments).strip()

        text_without_macros = re.sub(r"\{[^}]+\}", "", text_without_comments)
        text_without_macros = re.sub(r"\[[^\]]+\]", "", text_without_macros)
        text_without_macros = re.sub(r"<<[^>]+>>", "", text_without_macros)
        text_without_macros = re.sub(r"\[[^]]+\]", "", text_without_macros)
        text_without_macros = re.sub(r"https?://\S+", "", text_without_macros)

        clean_text = re.sub(r"[\*_]", "", text_without_macros)
        clean_text = restore_inline_code(clean_text, code_spans)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        if has_meaningful_text(clean_text):
            extracted_texts.append((original_line_number, line, clean_text))

    return extracted_texts


def extract_markdown_text(content: str) -> List[ExtractedLine]:
    """Extract reviewable prose lines from a Markdown document."""
    lines = content.split("\n")
    extracted_texts: List[ExtractedLine] = []
    in_code_block = False
    fence_character = None
    fence_length = 0

    for i, line in enumerate(lines):
        original_line_number = i + 1
        fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_match:
            marker, suffix = fence_match.groups()
            if not in_code_block:
                in_code_block = True
                fence_character = marker[0]
                fence_length = len(marker)
                continue
            if marker[0] == fence_character and len(marker) >= fence_length and not suffix.strip():
                in_code_block = False
                fence_character = None
                fence_length = 0
                continue

        if in_code_block:
            continue

        clean_text, code_spans = mask_inline_code(line)
        clean_text = re.sub(r"^#+\s*", "", clean_text)
        clean_text = re.sub(r"\[.*?\]\(.*?\)", "", clean_text)
        clean_text = re.sub(r"!?\[.*?\]\[.*?\]", "", clean_text)
        clean_text = re.sub(r"<.*?>", "", clean_text)
        clean_text = re.sub(r"(\*\*|__)(.*?)\1", "\\2", clean_text)
        clean_text = re.sub(r"(\*|_)(.*?)\1", "\\2", clean_text)
        clean_text = re.sub(r"~~(.*?)~~", "\\1", clean_text)
        clean_text = re.sub(r"^[\s]*[-*+]\s+", "", clean_text)
        clean_text = re.sub(r"^[\s]*\d+\.\s+", "", clean_text)
        clean_text = re.sub(r"^>\s*", "", clean_text)
        clean_text = re.sub(r"^[\s]*[-*_]{3,}[\s]*$", "", clean_text)
        clean_text = restore_inline_code(clean_text, code_spans)
        clean_text = re.sub(r"\s+", " ", clean_text).strip()

        if has_meaningful_text(clean_text):
            extracted_texts.append((original_line_number, line, clean_text))

    return extracted_texts


register_text_extractor((".adoc", ".asciidoc", ".asc", ".txt"), extract_asciidoc_text)
register_text_extractor((".md", ".markdown"), extract_markdown_text)


def unsupported_extension_warning(extension: str) -> None:
    logging.warning(f"Unsupported file type: {extension}")
