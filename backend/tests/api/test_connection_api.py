import pytest

from mbp.db import utcnow
from mbp.models import DbInstance
from mbp.services import mysql_probe
from mbp.services.mysql_probe import ProbeResult

PAYLOAD = {
    "name": "prod",
    "host": "db.internal",
    "port": 3306,
    "username": "backup",
    "password": "s3cret-pw",
}


@pytest.fixture
def probe(monkeypatch):
    """Controllable fake probe; records the params it was called with."""
    state = {"result": None, "calls": []}

    def test_connection(params, timeout=None):
        state["calls"].append(params)
        return state["result"]

    monkeypatch.setattr(mysql_probe, "test_connection", test_connection)
    return state


def ok_result():
    return ProbeResult(ok=True, tested_at=utcnow(), server_type="mysql", server_version="8.4.3")


def failed_result(code="auth_rejected"):
    return ProbeResult(ok=False, tested_at=utcnow(), error_code=code)


def test_unsaved_test_returns_result_and_stores_nothing(auth_client, db, probe):
    probe["result"] = ok_result()
    params = {k: PAYLOAD[k] for k in ("host", "port", "username", "password")}
    response = auth_client.post("/api/instances/test-connection", json=params)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert (body["server_type"], body["server_version"]) == ("mysql", "8.4.3")
    assert probe["calls"][0].password == "s3cret-pw"
    assert db.query(DbInstance).count() == 0


def test_unsaved_test_validates_input(auth_client, probe):
    response = auth_client.post(
        "/api/instances/test-connection", json={"host": "a b", "port": 0, "username": ""}
    )
    assert response.status_code == 422
    assert probe["calls"] == []


def test_saved_test_persists_detection(auth_client, db, probe):
    instance_id = auth_client.post("/api/instances", json=PAYLOAD).json()["id"]
    probe["result"] = ok_result()
    response = auth_client.post(f"/api/instances/{instance_id}/test-connection")
    assert response.status_code == 200
    assert probe["calls"][0].password == "s3cret-pw"

    stored = auth_client.get(f"/api/instances/{instance_id}").json()
    assert stored["server_type"] == "mysql"
    assert stored["server_version"] == "8.4.3"
    assert stored["last_test_ok"] is True
    assert stored["last_test_at"] is not None
    assert stored["last_test_error_code"] is None


def test_saved_test_failure_keeps_previous_detection(auth_client, probe):
    instance_id = auth_client.post("/api/instances", json=PAYLOAD).json()["id"]
    probe["result"] = ok_result()
    auth_client.post(f"/api/instances/{instance_id}/test-connection")

    probe["result"] = failed_result("timeout")
    body = auth_client.post(f"/api/instances/{instance_id}/test-connection").json()
    assert body["ok"] is False
    assert body["error_code"] == "timeout"

    stored = auth_client.get(f"/api/instances/{instance_id}").json()
    assert stored["last_test_ok"] is False
    assert stored["last_test_error_code"] == "timeout"
    assert stored["server_type"] == "mysql"


def test_saved_test_unknown_instance(auth_client, probe):
    assert auth_client.post("/api/instances/9999/test-connection").status_code == 404


def test_instance_deleted_during_test_discards_result(auth_client, db, probe, monkeypatch):
    instance_id = auth_client.post("/api/instances", json=PAYLOAD).json()["id"]

    def delete_then_succeed(params, timeout=None):
        with db.begin():
            db.delete(db.get(DbInstance, instance_id))
        return ok_result()

    monkeypatch.setattr(mysql_probe, "test_connection", delete_then_succeed)
    response = auth_client.post(f"/api/instances/{instance_id}/test-connection")
    assert response.status_code == 200
    assert auth_client.get(f"/api/instances/{instance_id}").status_code == 404
