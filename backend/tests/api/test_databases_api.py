import pytest

from mbp.models import DbSelection
from mbp.services import mysql_probe
from mbp.services.mysql_probe import ListResult

PAYLOAD = {
    "name": "prod",
    "host": "db.internal",
    "port": 3306,
    "username": "backup",
    "password": "s3cret-pw",
}


@pytest.fixture
def server(monkeypatch):
    """Fake server state used by the patched probe."""
    state = {"result": ListResult(ok=True, names=["information_schema", "mysql", "shop", "blog"])}
    monkeypatch.setattr(mysql_probe, "list_databases", lambda params, timeout=None: state["result"])
    return state


@pytest.fixture
def instance_id(auth_client):
    return auth_client.post("/api/instances", json=PAYLOAD).json()["id"]


def test_listing_reachable(auth_client, server, instance_id):
    body = auth_client.get(f"/api/instances/{instance_id}/databases").json()
    assert body["reachable"] is True
    entries = {d["name"]: d for d in body["databases"]}
    assert set(entries) == {"information_schema", "mysql", "shop", "blog"}
    assert entries["information_schema"] == {
        "name": "information_schema",
        "is_system": True,
        "selectable": False,
        "selected": False,
        "missing": False,
    }


def test_save_selection_and_reload(auth_client, server, instance_id, db):
    response = auth_client.put(
        f"/api/instances/{instance_id}/selection", json={"databases": ["shop", "blog"]}
    )
    assert response.status_code == 200
    selected = {d["name"] for d in response.json()["databases"] if d["selected"]}
    assert selected == {"shop", "blog"}

    body = auth_client.get(f"/api/instances/{instance_id}/databases").json()
    assert {d["name"] for d in body["databases"] if d["selected"]} == {"shop", "blog"}
    assert db.query(DbSelection).count() == 2


def test_dropped_database_shown_missing(auth_client, server, instance_id):
    auth_client.put(f"/api/instances/{instance_id}/selection", json={"databases": ["blog"]})
    server["result"] = ListResult(ok=True, names=["shop"])
    entries = {
        d["name"]: d
        for d in auth_client.get(f"/api/instances/{instance_id}/databases").json()["databases"]
    }
    assert entries["blog"]["missing"] is True
    assert entries["blog"]["selected"] is True


def test_unreachable_shape(auth_client, server, instance_id):
    auth_client.put(f"/api/instances/{instance_id}/selection", json={"databases": ["shop"]})
    server["result"] = ListResult(ok=False, error_code="connection_refused")
    body = auth_client.get(f"/api/instances/{instance_id}/databases").json()
    assert body["reachable"] is False
    assert body["error_code"] == "connection_refused"
    assert body["databases"] == [
        {"name": "shop", "is_system": False, "selectable": True, "selected": True, "missing": False}
    ]


@pytest.mark.parametrize(
    ("names", "code"),
    [(["information_schema"], "not_selectable"), (["nope"], "unknown_database")],
)
def test_selection_rejections(auth_client, server, instance_id, names, code):
    response = auth_client.put(f"/api/instances/{instance_id}/selection", json={"databases": names})
    assert response.status_code == 422
    assert response.json()["code"] == code


def test_duplicate_names_rejected(auth_client, server, instance_id):
    response = auth_client.put(
        f"/api/instances/{instance_id}/selection", json={"databases": ["shop", "shop"]}
    )
    assert response.status_code == 422


def test_unknown_instance(auth_client, server):
    assert auth_client.get("/api/instances/9999/databases").status_code == 404
    response = auth_client.put("/api/instances/9999/selection", json={"databases": []})
    assert response.status_code == 404
