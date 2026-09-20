"""Paths and timestamps for mutable DocSifter runtime state."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List


def utcnow() -> datetime:
    """Return a naive UTC timestamp, matching the existing SQLite columns.

    One base for every store. The two histories used to disagree: reviews were
    stored in UTC while local tasks used local time, so the same moment was
    recorded twice, hours apart.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def isoformat_utc(value: datetime | str | None) -> str | None:
    """Serialize a naive-UTC timestamp with an explicit offset.

    Without the offset a client parses the value as local time, which rendered
    review history eight hours early on a UTC+8 host. Values that already carry
    an offset are returned unchanged.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if not value:
            return value
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def get_data_dir() -> Path:
    """Return the writable data directory, creating it when necessary."""
    configured_dir = os.getenv("DOCSIFTER_DATA_DIR", "").strip()
    data_dir = Path(configured_dir).expanduser() if configured_dir else Path.cwd() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_runtime_path(*parts: str) -> str:
    """Return a path below the writable runtime directory."""
    path = get_data_dir().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_resource_path(filename: str) -> str:
    """Return a bundled, read-only resource shipped with the application."""
    return str(Path(__file__).resolve().parent / filename)


def get_allowed_roots() -> List[Path]:
    """Return filesystem roots that the Web UI may browse and review."""
    configured = os.getenv("DOCSIFTER_ALLOWED_ROOTS", "").strip()
    values = (
        [value for value in configured.split(os.pathsep) if value]
        if configured
        else [str(Path.cwd())]
    )
    return [Path(value).expanduser().resolve() for value in values]


def resolve_allowed_path(path: str, base_dir: str = None) -> Path:
    """Resolve a user path and reject paths outside the configured Web roots."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(base_dir or Path.cwd()) / candidate
    candidate = candidate.resolve()

    for root in get_allowed_roots():
        try:
            if os.path.commonpath([str(candidate), str(root)]) == str(root):
                return candidate
        except ValueError:
            continue

    raise PermissionError(f"Path is outside DOCSIFTER_ALLOWED_ROOTS: {candidate}")
