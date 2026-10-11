"""US5: global settings, per-instance overrides, validation and preview."""

import re

import pytest

from tests.conftest import create_instance, wait_for_run

DEFAULTS = {
    "storage_dir": "",
    "name_pattern": "{instance}/{database}_{date}_{time}",
    "compression": "gzip",
}


def test_defaults(auth_client):
    assert auth_client.get("/api/backup-settings").json() == DEFAULTS


def test_update_global(auth_client):
    body = {"storage_dir": "daily", "name_pattern": "{database}_{datetime}", "compression": "bzip2"}
    response = auth_client.put("/api/backup-settings", json=body)
    assert response.status_code == 200
    assert auth_client.get("/api/backup-settings").json() == body


@pytest.mark.parametrize(
    ("change", "field", "code"),
    [
        ({"name_pattern": "{instance}_{date}"}, "name_pattern", "missing_database"),
        ({"name_pattern": "{database}"}, "name_pattern", "missing_datetime"),
        ({"name_pattern": "{database}_{date}_{foo}"}, "name_pattern", "unknown_placeholder"),
        ({"storage_dir": "/etc"}, "storage_dir", "absolute_path"),
        ({"storage_dir": "../x"}, "storage_dir", "parent_segment"),
    ],
)
def test_validation(auth_client, change, field, code):
    response = auth_client.put("/api/backup-settings", json={**DEFAULTS, **change})
    assert response.status_code == 422
    assert response.json()["fields"] == {field: code}


def test_invalid_compression(auth_client):
    response = auth_client.put("/api/backup-settings", json={**DEFAULTS, "compression": "zip"})
    assert response.status_code == 422
    assert "compression" in response.json()["fields"]


def test_preview(auth_client):
    response = auth_client.post(
        "/api/backup-settings/preview",
        json={
            "storage_dir": "daily",
            "name_pattern": DEFAULTS["name_pattern"],
            "compression": "bzip2",
        },
    )
    assert response.status_code == 200
    assert re.fullmatch(
        r"daily/prod/shop_\d{4}-\d{2}-\d{2}_\d{6}\.sql\.bz2", response.json()["path"]
    )


def test_instance_overrides_and_effective(auth_client):
    instance_id = create_instance(auth_client)
    url = f"/api/instances/{instance_id}/backup-settings"
    body = auth_client.get(url).json()
    assert body["overrides"] == {"storage_dir": None, "name_pattern": None, "compression": None}
    assert body["effective"] == DEFAULTS

    body = auth_client.put(
        url, json={"storage_dir": "special", "name_pattern": None, "compression": "none"}
    ).json()
    assert body["effective"] == {**DEFAULTS, "storage_dir": "special", "compression": "none"}

    # Global changes still flow into inherited fields.
    auth_client.put("/api/backup-settings", json={**DEFAULTS, "name_pattern": "{database}_{date}"})
    assert auth_client.get(url).json()["effective"]["name_pattern"] == "{database}_{date}"

    bad = auth_client.put(url, json={"storage_dir": "../x"})
    assert bad.status_code == 422
    assert auth_client.get("/api/instances/9999/backup-settings").status_code == 404


def test_settings_change_does_not_touch_existing_runs(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    first = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_a"}
    ).json()["created"][0]["id"]
    before = wait_for_run(auth_client, first)

    auth_client.put(
        "/api/backup-settings",
        json={
            "storage_dir": "new",
            "name_pattern": "{database}_{datetime}",
            "compression": "bzip2",
        },
    )
    second = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_a"}
    ).json()["created"][0]["id"]
    after = wait_for_run(auth_client, second)

    unchanged = auth_client.get(f"/api/backups/runs/{first}").json()
    assert unchanged["compression"] == "gzip"
    assert unchanged["file_name"] == before["file_name"]
    assert unchanged["file_available"] is True
    assert after["compression"] == "bzip2"
    assert after["file_name"].endswith(".sql.bz2")
