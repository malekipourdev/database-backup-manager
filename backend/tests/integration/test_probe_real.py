import time

import pytest

from mbp.services import mysql_probe
from mbp.services.mysql_probe import ConnParams
from tests.integration.conftest import ROOT_PASSWORD

pytestmark = pytest.mark.integration


def params(server, **overrides) -> ConnParams:
    values = {
        "host": server.host,
        "port": server.port,
        "username": "root",
        "password": ROOT_PASSWORD,
    }
    values.update(overrides)
    return ConnParams(**values)


def test_success_detects_type_and_version(server):
    result = mysql_probe.test_connection(params(server))
    assert result.ok, result
    assert result.server_type == server.kind
    expected_prefix = server.image.split(":")[1] + "."
    assert result.server_version.startswith(expected_prefix)


def test_wrong_password(server):
    result = mysql_probe.test_connection(params(server, password="wrong-password"))
    assert result.error_code == "auth_rejected"


def test_closed_port(server):
    result = mysql_probe.test_connection(params(server, host="127.0.0.1", port=1))
    assert result.error_code == "connection_refused"


def test_unknown_host(server):
    result = mysql_probe.test_connection(params(server, host="nonexistent.invalid"))
    assert result.error_code == "host_not_found"


def test_blackholed_address_times_out_within_limit(server):
    started = time.monotonic()
    result = mysql_probe.test_connection(params(server, host="10.255.255.1"))
    elapsed = time.monotonic() - started
    # SC-004: every test returns within 12 seconds.
    assert elapsed < 12
    assert result.error_code in {"timeout", "connection_refused"}
