"""Scheduled backups: CRUD, validation, firing and the in-process scheduler."""

from datetime import UTC, datetime

import pytest

from mbp.backups.scheduler import fire_schedule, next_fire_times
from mbp.backups.store import get_store
from mbp.db import get_sessionmaker
from tests.conftest import create_instance, wait_for_run

DAILY = {"name": "nightly", "cron": "30 2 * * *", "timezone": "UTC", "scope": "all"}


def create_schedule(client, instance_id, **overrides):
    response = client.post(f"/api/instances/{instance_id}/schedules", json={**DAILY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_list_update_delete(auth_client, app):
    instance_id = create_instance(auth_client)
    created = create_schedule(auth_client, instance_id)
    assert created["instance_name"] == "prod"
    assert created["enabled"] is True
    next_run = datetime.fromisoformat(created["next_run_at"])
    assert (next_run.hour, next_run.minute) == (2, 30)

    # The in-process scheduler has a job for it.
    scheduler = app.state.backup_scheduler
    assert scheduler.next_run_time(created["id"]) == next_run

    listed = auth_client.get("/api/schedules").json()
    assert [s["id"] for s in listed] == [created["id"]]
    assert auth_client.get(f"/api/instances/{instance_id}/schedules").json()[0]["name"] == "nightly"

    updated = auth_client.put(
        f"/api/schedules/{created['id']}",
        json={**DAILY, "name": "weekly", "cron": "0 3 * * 1", "enabled": False},
    ).json()
    assert updated["name"] == "weekly"
    assert updated["next_run_at"] is None
    assert scheduler.next_run_time(created["id"]) is None

    assert auth_client.delete(f"/api/schedules/{created['id']}").status_code == 204
    assert auth_client.get(f"/api/schedules/{created['id']}").status_code == 404


def test_timezone_is_respected(auth_client):
    instance_id = create_instance(auth_client)
    created = create_schedule(auth_client, instance_id, cron="0 2 * * *", timezone="Asia/Tehran")
    next_run = datetime.fromisoformat(created["next_run_at"]).astimezone(UTC)
    # 02:00 in Tehran (UTC+03:30) is 22:30 UTC.
    assert (next_run.hour, next_run.minute) == (22, 30)


@pytest.mark.parametrize(
    ("overrides", "field", "code"),
    [
        ({"cron": "not a cron"}, "cron", "invalid_cron"),
        ({"cron": "61 * * * *"}, "cron", "invalid_cron"),
        ({"cron": "* * * *"}, "cron", "invalid_cron"),
        ({"timezone": "Mars/Base"}, "timezone", "invalid_timezone"),
        ({"scope": "single"}, "database", "required"),
        ({"scope": "single", "database": "sys"}, "database", "not_selectable"),
    ],
)
def test_validation(auth_client, overrides, field, code):
    instance_id = create_instance(auth_client)
    response = auth_client.post(
        f"/api/instances/{instance_id}/schedules", json={**DAILY, **overrides}
    )
    assert response.status_code == 422
    assert response.json()["fields"] == {field: code}


def test_option_like_database_rejected(auth_client):
    instance_id = create_instance(auth_client)
    response = auth_client.post(
        f"/api/instances/{instance_id}/schedules",
        json={**DAILY, "scope": "single", "database": "--plugin-dir=/x"},
    )
    assert response.status_code == 422


def test_unknown_instance(auth_client):
    assert auth_client.post("/api/instances/999/schedules", json=DAILY).status_code == 404
    assert auth_client.get("/api/instances/999/schedules").status_code == 404


def test_preview(auth_client):
    response = auth_client.post("/api/schedules/preview", json={"cron": "*/15 * * * *"})
    assert response.status_code == 200
    runs = [datetime.fromisoformat(t) for t in response.json()["next_runs"]]
    assert len(runs) == 5
    assert all((b - a).total_seconds() == 900 for a, b in zip(runs, runs[1:], strict=False))
    bad = auth_client.post("/api/schedules/preview", json={"cron": "bad"})
    assert bad.status_code == 422


def test_next_fire_times_helper():
    start = datetime(2026, 10, 11, 10, 0, tzinfo=UTC)
    times = next_fire_times("0 * * * *", "UTC", count=3, now=start)
    assert [t.hour for t in times] == [10, 11, 12]


def _fire(app, schedule_id):
    return fire_schedule(schedule_id, get_sessionmaker(), app.state.backup_runner, get_store())


def test_firing_queues_backups_of_marked_databases(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop", "ok_blog"))
    schedule = create_schedule(auth_client, instance_id)
    assert _fire(app, schedule["id"]) == "queued"

    runs = auth_client.get(f"/api/backups/runs?instance_id={instance_id}").json()["items"]
    assert len(runs) == 2
    assert all(r["trigger"] == "schedule" and r["schedule_id"] == schedule["id"] for r in runs)
    for run in runs:
        assert wait_for_run(auth_client, run["id"])["status"] == "success"

    body = auth_client.get(f"/api/schedules/{schedule['id']}").json()
    assert body["last_result"] == "queued"
    assert body["last_fired_at"] is not None


def test_firing_single_database(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client)
    schedule = create_schedule(auth_client, instance_id, scope="single", database="ok_other")
    assert _fire(app, schedule["id"]) == "queued"
    runs = auth_client.get("/api/backups/runs").json()["items"]
    assert [r["database_name"] for r in runs] == ["ok_other"]
    wait_for_run(auth_client, runs[0]["id"])


def test_firing_with_nothing_marked_is_recorded(auth_client, app):
    instance_id = create_instance(auth_client)
    schedule = create_schedule(auth_client, instance_id)
    assert _fire(app, schedule["id"]) == "no_databases_selected"
    body = auth_client.get(f"/api/schedules/{schedule['id']}").json()
    assert body["last_result"] == "no_databases_selected"


def test_firing_while_backup_running_is_skipped(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client, select=("slow_2_db",))
    schedule = create_schedule(auth_client, instance_id)
    assert _fire(app, schedule["id"]) == "queued"
    assert _fire(app, schedule["id"]) == "already_in_progress"
    body = auth_client.get(f"/api/schedules/{schedule['id']}").json()
    assert body["last_detail"] == "slow_2_db"
    run = auth_client.get("/api/backups/runs").json()["items"][0]
    wait_for_run(auth_client, run["id"])


def test_disabled_schedule_does_not_fire(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop",))
    schedule = create_schedule(auth_client, instance_id, enabled=False)
    assert _fire(app, schedule["id"]) is None
    assert auth_client.get("/api/backups/runs").json()["total"] == 0


def test_deleting_instance_removes_its_schedules(auth_client, app):
    instance_id = create_instance(auth_client)
    schedule = create_schedule(auth_client, instance_id)
    assert app.state.backup_scheduler.next_run_time(schedule["id"]) is not None
    assert auth_client.delete(f"/api/instances/{instance_id}").status_code == 204
    assert auth_client.get("/api/schedules").json() == []
    assert app.state.backup_scheduler.next_run_time(schedule["id"]) is None


def test_runs_keep_history_after_schedule_deleted(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop",))
    schedule = create_schedule(auth_client, instance_id)
    _fire(app, schedule["id"])
    run = auth_client.get("/api/backups/runs").json()["items"][0]
    wait_for_run(auth_client, run["id"])
    auth_client.delete(f"/api/schedules/{schedule['id']}")
    after = auth_client.get(f"/api/backups/runs/{run['id']}").json()
    assert after["trigger"] == "schedule"
    assert after["schedule_id"] is None


def test_scheduler_job_fires_on_time(auth_client, app, probe_ok):
    import time

    instance_id = create_instance(auth_client, select=("ok_shop",))
    schedule = create_schedule(auth_client, instance_id)
    job = app.state.backup_scheduler._scheduler.get_job(f"schedule-{schedule['id']}")
    job.modify(next_run_time=datetime.now(UTC))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        items = auth_client.get("/api/backups/runs").json()["items"]
        if items:
            break
        time.sleep(0.05)
    assert items and items[0]["trigger"] == "schedule"
    assert wait_for_run(auth_client, items[0]["id"])["status"] == "success"
