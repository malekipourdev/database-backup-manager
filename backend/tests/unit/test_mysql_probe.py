import socket
import time

import pymysql
import pytest

from mbp.services import mysql_probe
from mbp.services.mysql_probe import ConnParams, classify_error, detect_server_type, parse_version

PARAMS = ConnParams(host="db", port=3306, username="u", password="Pw-Secret-1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8.4.3", "8.4.3"),
        ("8.0.39-0ubuntu0.22.04.1", "8.0.39"),
        ("11.8.2-MariaDB-ubu2404", "11.8.2"),
        ("5.5.5-10.11.6-MariaDB", "10.11.6"),
    ],
)
def test_parse_version(raw, expected):
    assert parse_version(raw) == expected


@pytest.mark.parametrize(
    ("version", "comment", "expected"),
    [
        ("8.4.3", "MySQL Community Server - GPL", "mysql"),
        ("11.8.2-MariaDB-ubu2404", "mariadb.org binary distribution", "mariadb"),
        ("10.6.5", "MariaDB Server", "mariadb"),
        ("8.0.36", None, "mysql"),
    ],
)
def test_detect_server_type(version, comment, expected):
    assert detect_server_type(version, comment) == expected


def _wrapped(original: BaseException) -> pymysql.err.OperationalError:
    # Mirrors how PyMySQL wraps socket errors during connect.
    exc = pymysql.err.OperationalError(2003, f"Can't connect to MySQL server on 'db' ({original})")
    exc.original_exception = original
    return exc


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (socket.gaierror(-2, "Name or service not known"), "host_not_found"),
        (_wrapped(socket.gaierror(-2, "Name or service not known")), "host_not_found"),
        (_wrapped(ConnectionRefusedError(111, "Connection refused")), "connection_refused"),
        (_wrapped(TimeoutError("timed out")), "timeout"),
        (TimeoutError(), "timeout"),
        (pymysql.err.OperationalError(2003, "Can't connect (timed out)"), "timeout"),
        (pymysql.err.OperationalError(1045, "Access denied for user 'u'"), "auth_rejected"),
        (pymysql.err.OperationalError(1044, "Access denied to database"), "auth_rejected"),
        (pymysql.err.OperationalError(1698, "Access denied"), "auth_rejected"),
        (pymysql.err.OperationalError(1129, "Host is blocked"), "server_error"),
        (pymysql.err.InternalError(1105, "Unknown error"), "server_error"),
    ],
)
def test_classify_error(exc, code):
    assert classify_error(exc, PARAMS.password)[0] == code


def test_sanitize_removes_password_and_truncates():
    exc = pymysql.err.OperationalError(1105, f"weird {PARAMS.password} " + "x" * 1000)
    code, detail = classify_error(exc, PARAMS.password)
    assert code == "server_error"
    assert PARAMS.password not in detail
    assert len(detail) == 500


def test_success_detects_type_and_version(monkeypatch):
    monkeypatch.setattr(
        mysql_probe, "_query", lambda *a: [("11.8.2-MariaDB-ubu2404", "mariadb.org")]
    )
    result = mysql_probe.test_connection(PARAMS)
    assert result.ok
    assert (result.server_type, result.server_version) == ("mariadb", "11.8.2")
    assert result.error_code is None


def test_failure_is_classified(monkeypatch):
    def boom(*args):
        raise pymysql.err.OperationalError(1045, "Access denied")

    monkeypatch.setattr(mysql_probe, "_query", boom)
    result = mysql_probe.test_connection(PARAMS)
    assert not result.ok
    assert result.error_code == "auth_rejected"


def test_deadline_maps_to_timeout(monkeypatch):
    # A connect that hangs past the deadline (e.g. slow DNS) is reported as a timeout.
    monkeypatch.setattr(mysql_probe, "_connect", lambda params, timeout: time.sleep(3))
    started = time.monotonic()
    result = mysql_probe.test_connection(PARAMS, timeout=1)
    assert time.monotonic() - started < 2
    assert result.error_code == "timeout"


def test_list_databases(monkeypatch):
    monkeypatch.setattr(mysql_probe, "_query", lambda *a: [("shop",), ("mysql",)])
    result = mysql_probe.list_databases(PARAMS)
    assert result.ok
    assert result.names == ["shop", "mysql"]


def test_conn_params_repr_hides_password():
    assert PARAMS.password not in repr(PARAMS)
