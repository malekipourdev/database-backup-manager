import time

import pytest

from tests.integration.conftest import ROOT_PASSWORD

pytestmark = pytest.mark.integration


def register(auth_client, server, username="root", password=ROOT_PASSWORD) -> int:
    response = auth_client.post(
        "/api/instances",
        json={
            "name": f"{server.kind}-{username}",
            "host": server.host,
            "port": server.port,
            "username": username,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def listing(auth_client, instance_id) -> dict[str, dict]:
    body = auth_client.get(f"/api/instances/{instance_id}/databases").json()
    assert body["reachable"], body
    return {d["name"]: d for d in body["databases"]}


def test_saved_instance_connection_test(auth_client, server):
    instance_id = register(auth_client, server)
    body = auth_client.post(f"/api/instances/{instance_id}/test-connection").json()
    assert body["ok"] is True
    stored = auth_client.get(f"/api/instances/{instance_id}").json()
    assert stored["server_type"] == server.kind


def test_list_select_and_missing(auth_client, server):
    server.execute(
        "DROP DATABASE IF EXISTS shop",
        "DROP DATABASE IF EXISTS blog",
        "CREATE DATABASE shop",
        "CREATE DATABASE blog",
    )
    instance_id = register(auth_client, server)

    entries = listing(auth_client, instance_id)
    assert {"shop", "blog"} <= set(entries)
    for name in ("information_schema", "performance_schema", "mysql", "sys"):
        if name in entries:
            assert entries[name]["is_system"], name

    response = auth_client.put(
        f"/api/instances/{instance_id}/selection", json={"databases": ["shop", "blog"]}
    )
    assert response.status_code == 200, response.text

    server.execute("DROP DATABASE blog")
    entries = listing(auth_client, instance_id)
    assert entries["blog"]["missing"] and entries["blog"]["selected"]
    assert not entries["shop"]["missing"]


def test_listing_respects_user_privileges(auth_client, server):
    server.execute(
        "CREATE DATABASE IF NOT EXISTS shop",
        "CREATE DATABASE IF NOT EXISTS secret_db",
        "DROP USER IF EXISTS 'limited'@'%'",
        "CREATE USER 'limited'@'%' IDENTIFIED BY 'Limited-Pass-1'",
        "GRANT SELECT ON shop.* TO 'limited'@'%'",
    )
    instance_id = register(auth_client, server, username="limited", password="Limited-Pass-1")
    names = set(listing(auth_client, instance_id))
    assert "shop" in names
    assert "secret_db" not in names


def test_many_databases_listed_quickly(auth_client, server):
    # SC-006: 500+ databases listed within 5 seconds.
    server.execute(*(f"CREATE DATABASE IF NOT EXISTS bulk_{i:03d}" for i in range(500)))
    instance_id = register(auth_client, server)
    started = time.monotonic()
    names = set(listing(auth_client, instance_id))
    assert time.monotonic() - started < 5
    assert {f"bulk_{i:03d}" for i in range(500)} <= names
