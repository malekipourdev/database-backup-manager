"""Backup file naming: pattern validation, rendering and file-name sanitizing."""

import re
from datetime import datetime
from pathlib import PurePosixPath

ALLOWED_PLACEHOLDERS = frozenset(
    {"instance", "database", "date", "time", "datetime", "server_type"}
)
DATETIME_PLACEHOLDERS = frozenset({"date", "time", "datetime"})
EXTENSIONS = {"gzip": ".sql.gz", "bzip2": ".sql.bz2", "none": ".sql"}
COMPRESSIONS = tuple(EXTENSIONS)
MAX_SETTING_LENGTH = 255
MAX_SEGMENT_BYTES = 120

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_UNSAFE_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f\s]')


def _segment_error(segment: str) -> str | None:
    if segment in ("..", "."):
        return "parent_segment"
    if segment == "":
        return "empty_segment"
    if any(ord(ch) < 32 or ch == "\x7f" for ch in segment):
        return "invalid_character"
    return None


def validate_storage_dir(value: str) -> str | None:
    """Return an error code, or None if the relative storage directory is acceptable."""
    if value == "":
        return None
    if len(value) > MAX_SETTING_LENGTH:
        return "too_long"
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        return "absolute_path"
    if "\\" in value:
        return "invalid_character"
    for segment in value.split("/"):
        error = _segment_error(segment)
        if error:
            return error
    return None


def validate_pattern(value: str) -> str | None:
    """Return an error code, or None if the naming pattern is acceptable."""
    if not value.strip():
        return "required"
    if len(value) > MAX_SETTING_LENGTH:
        return "too_long"
    if value.startswith(("/", "\\")):
        return "absolute_path"
    for segment in value.split("/"):
        error = _segment_error(segment)
        if error:
            return error
    names = set(_PLACEHOLDER_RE.findall(value))
    leftover = _PLACEHOLDER_RE.sub("", value)
    if names - ALLOWED_PLACEHOLDERS or "{" in leftover or "}" in leftover:
        return "unknown_placeholder"
    if "database" not in names:
        return "missing_database"
    if not names & DATETIME_PLACEHOLDERS:
        return "missing_datetime"
    return None


def sanitize_segment(value: str) -> str:
    """Make one path segment safe: replace unsafe characters, keep Unicode letters."""
    cleaned = _UNSAFE_RE.sub("_", value)
    if cleaned.startswith("."):
        cleaned = "_" + cleaned[1:]
    encoded = cleaned.encode("utf-8")[:MAX_SEGMENT_BYTES]
    cleaned = encoded.decode("utf-8", errors="ignore")
    return cleaned or "_"


def render(
    pattern: str,
    *,
    instance: str,
    database: str,
    server_type: str | None,
    now: datetime,
    compression: str,
) -> PurePosixPath:
    """Render a validated pattern into a relative path (UTC times, extension appended)."""
    values = {
        "instance": instance,
        "database": database,
        "server_type": server_type or "unknown",
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H%M%S"),
        "datetime": now.strftime("%Y-%m-%d_%H%M%S"),
    }
    segments = []
    for segment in pattern.split("/"):
        # Substitute per segment so "/" inside a name can never create directories.
        rendered = _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], segment)
        segments.append(sanitize_segment(rendered))
    max_last = MAX_SEGMENT_BYTES - len(EXTENSIONS[compression])
    last = segments[-1].encode("utf-8")[:max_last].decode("utf-8", errors="ignore")
    segments[-1] = last + EXTENSIONS[compression]
    return PurePosixPath(*segments)
