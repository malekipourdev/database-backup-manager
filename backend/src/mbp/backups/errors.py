"""Maps dump failures to stable error codes with sanitized, readable messages."""

import errno
import re

MAX_MESSAGE = 1000

_PRIVILEGE_CODES = ("1044", "1142", "1227", "1143", "1370")
_CONNECTION_CODES = ("2002", "2003", "2005", "2006", "2013")

VERIFY_MESSAGES = {
    "checksum_mismatch": "The file changed on disk after it was written (checksum mismatch).",
    "corrupt": "The compressed file could not be read back completely (archive is corrupt).",
    "no_marker": "The dump ended without its completion marker; the output is incomplete.",
}


def sanitize(message: str, password: str | None) -> str:
    if password:
        message = message.replace(password, "***")
    return message.strip()[-MAX_MESSAGE:]


def _error_lines(stderr: str) -> str:
    # Warnings (e.g. about insecure options) are noise; keep the actual error lines.
    lines = [line for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if "warning" not in line.lower()]
    return "\n".join((errors or lines)[-5:])


def _has_code(text: str, codes: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{code}\b", text) for code in codes)


def classify_dump_failure(returncode: int, stderr: str, password: str | None) -> tuple[str, str]:
    """(error_code, message) for a dump process that exited unsuccessfully."""
    detail = sanitize(_error_lines(stderr), password) or f"dump tool exited with code {returncode}"
    lowered = stderr.lower()
    if _has_code(stderr, ("1045",)):
        return "auth_rejected", detail
    if _has_code(stderr, _PRIVILEGE_CODES) or "access denied" in lowered:
        return "missing_privileges", detail
    if _has_code(stderr, ("1049",)) or "unknown database" in lowered:
        return "database_not_found", detail
    if _has_code(stderr, _CONNECTION_CODES) or "lost connection" in lowered:
        return "connection_lost", detail
    return "dump_failed", detail


def classify_os_error(exc: OSError) -> tuple[str, str]:
    if exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return "disk_full", "Not enough disk space in the backup storage area."
    return "storage_error", f"Could not write the backup file: {exc.strerror or exc}"
