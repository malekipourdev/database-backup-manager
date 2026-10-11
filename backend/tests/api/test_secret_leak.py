"""SC-003: a stored instance password never appears in any response or log record."""

import logging

import pytest

from mbp.services import mysql_probe
from mbp.services.mysql_probe import ListResult, ProbeResult

CANARY = "Leak-Canary-9f3b"


@pytest.fixture
def fake_probe(monkeypatch):
    """Probe that fails with a server message echoing the password, like a hostile server."""

    def test_connection(params, timeout=None):
        assert params.password == CANARY  # the real password does reach the probe
        _, detail = mysql_probe.classify_error(
            Exception(f"bad handshake for password {params.password}"), params.password
        )
        return ProbeResult(
            ok=False,
            tested_at=mysql_probe.utcnow(),
            error_code="server_error",
            error_detail=detail,
        )

    def list_databases(params, timeout=None):
        logging.getLogger("mbp.test").info("listing databases on %s", params.host)
        return ListResult(ok=True, names=["shop"])

    monkeypatch.setattr(mysql_probe, "test_connection", test_connection)
    monkeypatch.setattr(mysql_probe, "list_databases", list_databases)


def test_password_never_leaks(auth_client, caplog, fake_probe):
    caplog.set_level(logging.DEBUG)
    payload = {
        "name": "prod",
        "host": "db.internal",
        "port": 3306,
        "username": "backup",
        "password": CANARY,
    }
    responses = [auth_client.post("/api/instances", json=payload)]
    instance_id = responses[0].json()["id"]
    base = f"/api/instances/{instance_id}"

    responses += [
        auth_client.get("/api/instances"),
        auth_client.get(base),
        auth_client.patch(base, json={"notes": "x"}),
        auth_client.patch(base, json={"port": 0, "password": CANARY}),  # validation error
        auth_client.post("/api/instances", json={**payload, "host": "bad host"}),  # 422
        auth_client.post("/api/instances", json=payload),  # 409 name taken
        auth_client.post(f"{base}/test-connection"),
        auth_client.post(
            "/api/instances/test-connection",
            json={k: payload[k] for k in ("host", "port", "username", "password")},
        ),
        auth_client.get(f"{base}/databases"),
        auth_client.put(f"{base}/selection", json={"databases": ["shop"]}),
        auth_client.delete(base),
    ]

    for response in responses:
        assert CANARY not in response.text, response.request.url
    assert all(CANARY not in record.getMessage() for record in caplog.records)
    assert CANARY not in caplog.text
