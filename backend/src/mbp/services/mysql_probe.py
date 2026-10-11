"""Read-only access to target MySQL/MariaDB servers: connection test and database listing."""

import concurrent.futures
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import pymysql

from mbp.config import get_settings
from mbp.db import utcnow

AUTH_ERROR_CODES = frozenset({1044, 1045, 1698})
MAX_DETAIL_LENGTH = 500

# Bounded pool: a server that hangs ties up at most this many threads, and the
# per-socket timeouts below make every worker finish on its own shortly after.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="mbp-probe")


@dataclass(frozen=True)
class ConnParams:
    host: str
    port: int
    username: str
    password: str = field(repr=False)


@dataclass
class ProbeResult:
    ok: bool
    tested_at: datetime
    server_type: str | None = None
    server_version: str | None = None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass
class ListResult:
    ok: bool
    names: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None


def parse_version(raw: str) -> str:
    # MariaDB may report "5.5.5-10.11.6-MariaDB" for replication compatibility.
    if raw.startswith("5.5.5-"):
        raw = raw[len("5.5.5-") :]
    match = re.match(r"(\d+\.\d+\.\d+)", raw)
    return match.group(1) if match else raw[:64]


def detect_server_type(version: str, version_comment: str | None) -> str:
    text = f"{version} {version_comment or ''}".lower()
    return "mariadb" if "mariadb" in text else "mysql"


def sanitize(message: str, password: str) -> str:
    if password:
        message = message.replace(password, "***")
    return message[:MAX_DETAIL_LENGTH]


def _classify_os_error(exc: BaseException) -> str | None:
    if isinstance(exc, socket.gaierror):
        return "host_not_found"
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(exc, TimeoutError | socket.timeout):
        return "timeout"
    if isinstance(exc, OSError):
        return "connection_refused"
    return None


def classify_error(exc: BaseException, password: str) -> tuple[str, str | None]:
    """Map an exception to (error_code, sanitized detail)."""
    if isinstance(exc, concurrent.futures.TimeoutError | TimeoutError | socket.timeout):
        return "timeout", None
    if isinstance(exc, pymysql.err.MySQLError):
        original = getattr(exc, "original_exception", None)
        if original is not None:
            code = _classify_os_error(original)
            if code:
                return code, None
        errno = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
        message = str(exc.args[1]) if len(exc.args) > 1 else str(exc)
        if errno in AUTH_ERROR_CODES:
            return "auth_rejected", None
        if errno == 2005:
            return "host_not_found", None
        if errno in (2003, 2013) and "timed out" in message.lower():
            return "timeout", None
        if errno == 2003 and "refused" in message.lower():
            return "connection_refused", None
        return "server_error", sanitize(message, password)
    code = _classify_os_error(exc)
    if code:
        return code, None
    return "server_error", sanitize(str(exc), password)


def _connect(params: ConnParams, timeout: int) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=params.host,
        port=params.port,
        user=params.username,
        password=params.password,
        connect_timeout=timeout,
        read_timeout=timeout,
        write_timeout=timeout,
        charset="utf8mb4",
        autocommit=True,
    )


def _with_deadline[T](work: Callable[[], T], timeout: int) -> T:
    # Overall deadline also covers slow DNS resolution, which socket timeouts do not.
    return _executor.submit(work).result(timeout=timeout)


def _query(params: ConnParams, timeout: int, sql: str) -> list[tuple]:
    def work() -> list[tuple]:
        conn = _connect(params, timeout)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                return list(cursor.fetchall())
        finally:
            conn.close()

    return _with_deadline(work, timeout)


def test_connection(params: ConnParams, timeout: int | None = None) -> ProbeResult:
    timeout = timeout or get_settings().connect_timeout_seconds
    try:
        rows = _query(params, timeout, "SELECT VERSION(), @@version_comment")
    except Exception as exc:
        code, detail = classify_error(exc, params.password)
        return ProbeResult(ok=False, tested_at=utcnow(), error_code=code, error_detail=detail)
    version, comment = rows[0]
    return ProbeResult(
        ok=True,
        tested_at=utcnow(),
        server_type=detect_server_type(str(version), comment),
        server_version=parse_version(str(version)),
    )


# Keep pytest from collecting this function when a test module imports it.
test_connection.__test__ = False  # type: ignore[attr-defined]


def list_databases(params: ConnParams, timeout: int | None = None) -> ListResult:
    timeout = timeout or get_settings().connect_timeout_seconds
    try:
        rows = _query(params, timeout, "SHOW DATABASES")
    except Exception as exc:
        code, detail = classify_error(exc, params.password)
        return ListResult(ok=False, error_code=code, error_detail=detail)
    return ListResult(ok=True, names=[str(row[0]) for row in rows])
