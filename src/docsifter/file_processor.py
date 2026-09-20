#!/usr/bin/env python3
"""File discovery and reading helpers for documentation reviews."""

import logging
import os
import re
import stat
from pathlib import Path
from typing import Generator, Iterable, List, Tuple

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "venv",
    }
)


DEFAULT_MAX_FILE_SIZE_MB = 5


class FileProcessor:
    def __init__(
        self,
        skip_patterns: List[str] | None = None,
        excluded_directories: Iterable[str] | None = None,
        max_file_size_mb: int | None = None,
    ):
        self.max_file_size_bytes = int(max_file_size_mb or DEFAULT_MAX_FILE_SIZE_MB) * 1024 * 1024
        self.skip_patterns = skip_patterns or []
        self.compiled_skip_patterns = [re.compile(pattern) for pattern in self.skip_patterns]
        self.excluded_directories = (
            set(DEFAULT_EXCLUDED_DIRECTORIES)
            if excluded_directories is None
            else set(excluded_directories)
        )

    def should_skip_file(self, file_path: str) -> bool:
        for pattern in self.compiled_skip_patterns:
            if pattern.search(file_path):
                return True
        return False

    def should_skip_directory(self, directory_path: str) -> bool:
        name = Path(directory_path).name
        return (
            name in self.excluded_directories
            or name.endswith(("-venv", "_venv"))
            or self.should_skip_file(directory_path)
        )

    def get_all_supported_files(self, path: str) -> List[str]:
        supported_files = []
        path_obj = Path(path)

        if not path_obj.exists():
            logger.warning("path does not exist: %s", path)
            return supported_files

        supported_extensions = {".adoc", ".asciidoc", ".asc", ".txt", ".md", ".markdown"}

        if path_obj.is_file():
            if path_obj.suffix.lower() in supported_extensions:
                if not self.should_skip_file(str(path_obj)) and self.is_reviewable_file(
                    str(path_obj)
                ):
                    supported_files.append(str(path_obj))
            return supported_files

        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not self.should_skip_directory(os.path.join(root, d))]

            for file in files:
                file_path = os.path.join(root, file)
                if Path(file).suffix.lower() in supported_extensions:
                    if not self.should_skip_file(file_path) and self.is_reviewable_file(file_path):
                        supported_files.append(file_path)

        return sorted(supported_files)

    def is_reviewable_file(self, file_path: str) -> bool:
        """Reject anything that is not a plain file of reasonable size.

        A symlink inside a documentation tree resolves outside the tree being
        reviewed, and reading follows it. One pointing at a character device
        never returns, and reviews run one at a time under a shared lock, so a
        single such file in a pull request would stall every later review.
        """
        try:
            info = os.lstat(file_path)
        except OSError as e:
            logger.warning("skipping unreadable file %s: %s", file_path, e)
            return False

        if stat.S_ISLNK(info.st_mode):
            logger.debug("skipping symbolic link: %s", file_path)
            return False

        if not stat.S_ISREG(info.st_mode):
            logger.debug("skipping non-regular file: %s", file_path)
            return False

        if info.st_size > self.max_file_size_bytes:
            limit_mb = self.max_file_size_bytes / 1024 / 1024
            logger.warning(
                "skipping %s: %.1f MB exceeds the %.0f MB review limit",
                file_path,
                info.st_size / 1024 / 1024,
                limit_mb,
            )
            return False

        return True

    def read_file_content(self, file_path: str) -> str:
        # The GitHub path builds its file list from the pull request's changed
        # files rather than from get_all_supported_files, so the guard belongs
        # here where both paths pass through.
        if not self.is_reviewable_file(file_path):
            return ""

        try:
            with open(file_path, encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, encoding="gbk") as f:
                    return f.read()
            except Exception as e:
                logger.warning("failed to read file %s: %s", file_path, e)
                return ""
        except Exception as e:
            logger.warning("failed to read file %s: %s", file_path, e)
            return ""

    def scan_directory(self, directory_path: str) -> Generator[Tuple[str, str], None, None]:
        logger.info("scanning directory: %s", directory_path)
        supported_files = self.get_all_supported_files(directory_path)
        for file_path in supported_files:
            content = self.read_file_content(file_path)
            if content:
                yield file_path, content
