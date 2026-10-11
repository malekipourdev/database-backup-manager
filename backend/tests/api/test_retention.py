"""Retention: expiry rules, local deletion, records of what was deleted."""

from datetime import UTC, datetime, timedelta

import pytest

from mbp.backups.store import get_store
from mbp.db import get_sessionmaker
from mbp.models import BackupRun
from mbp.services.retention_service import RetentionPolicy, RetentionService, expired
from tests.conftest import BACKUP_ROOT, create_instance, wait_for_run

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def make_runs(ages_days):
    """Successful runs (newest first) finished `age` days before NOW."""
    return [
        BackupRun(id=i + 1, finished_at=NOW - timedelta(days=age), requested_at=NOW)
        for i, age in enumerate(ages_days)
    ]


@pytest.mark.parametrize(
    ("policy", "ages", "expected_ids"),
    [
        (RetentionPolicy(), [0, 1, 2], []),
        (RetentionPolicy(keep_last=2), [0, 1, 2, 3], [3, 4]),
        (RetentionPolicy(keep_last=1), [0, 1], [2]),
        (RetentionPolicy(max_age_days=7), [0, 3, 8, 30], [3, 4]),
        # The newest backup is kept even when it is older than the age limit.
        (RetentionPolicy(max_age_days=7), [10, 20], [2]),
        # Either rule expires a backup.
        (RetentionPolicy(keep_last=3, max_age_days=7), [0, 1, 8, 9], [3, 4]),
        (RetentionPolicy(keep_last=2, max_age_days=30), [0, 1, 2], [3]),
    ],
)
def test_expiry_rules(policy, ages, expected_ids):
    assert [r.id for r in expired(make_runs(ages), policy, NOW)] == expected_ids


def seed_success(instance_id, database, age_days, name="prod", content=b"x"):
    """A finished, successful run with a real local file."""
    relative = f"{name}/{database}_{age_days}.sql.gz"
    path = BACKUP_ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    finished = datetime.now(UTC) - timedelta(days=age_days)
    with get_sessionmaker()() as db:
        run = BackupRun(
            instance_id=instance_id,
            instance_name=name,
            database_name=database,
            trigger="single",
            status="success",
            requested_at=finished,
            started_at=finished,
            finished_at=finished,
            bytes_processed=1,
            file_size=len(content),
            compression="gzip",
            checksum_sha256="0" * 64,
            file_path=relative,
        )
        db.add(run)
        db.commit()
        return run.id, path


def set_policy(client, **policy):
    response = client.put("/api/retention", json=policy)
    assert response.status_code == 200, response.text
    return response.json()


def test_global_policy_roundtrip(auth_client):
    body = auth_client.get("/api/retention").json()
    assert body == {
        "local_keep_last": None,
        "local_max_age_days": None,
        "remote_keep_last": None,
        "remote_max_age_days": None,
    }
    saved = set_policy(auth_client, local_keep_last=5, remote_max_age_days=90)
    assert saved["local_keep_last"] == 5
    assert saved["remote_max_age_days"] == 90
    # Saving retention must not touch the other backup settings.
    assert auth_client.get("/api/backup-settings").json()["compression"] == "gzip"
    assert auth_client.put("/api/retention", json={"local_keep_last": 0}).status_code == 422


def test_dry_run_reports_without_deleting(auth_client):
    instance_id = create_instance(auth_client)
    ids = [seed_success(instance_id, "shop", age)[0] for age in (0, 1, 2)]
    set_policy(auth_client, local_keep_last=1)
    report = auth_client.post("/api/retention/apply", json={"dry_run": True}).json()
    assert report["dry_run"] is True
    assert sorted(item["run_id"] for item in report["deleted"]) == sorted(ids[1:])
    assert all(item["target"] == "local" for item in report["deleted"])
    assert len(list(BACKUP_ROOT.rglob("*.sql.gz"))) == 3


def test_apply_deletes_files_and_records_it(auth_client):
    instance_id = create_instance(auth_client)
    seeded = [seed_success(instance_id, "shop", age) for age in (0, 10, 40)]
    seed_success(instance_id, "blog", 50)  # the only (newest) backup of blog: always kept
    set_policy(auth_client, local_max_age_days=30)

    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert [item["run_id"] for item in report["deleted"]] == [seeded[2][0]]
    assert report["errors"] == []
    assert not seeded[2][1].exists()
    assert seeded[0][1].exists() and seeded[1][1].exists()

    run = auth_client.get(f"/api/backups/runs/{seeded[2][0]}").json()
    assert run["status"] == "success"
    assert run["file_deleted_reason"] == "retention"
    assert run["file_deleted_at"] is not None
    assert run["file_available"] is False
    assert run["download_available"] is False
    download = auth_client.get(f"/api/backups/runs/{seeded[2][0]}/download")
    assert download.status_code == 409

    # Applying again finds nothing more to delete.
    again = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert again["deleted"] == []


def test_instance_override(auth_client):
    keep = create_instance(auth_client, name="keep")
    trim = create_instance(auth_client, name="trim")
    for instance_id, name in ((keep, "keep"), (trim, "trim")):
        for age in (0, 1, 2):
            seed_success(instance_id, "shop", age, name=name)
    set_policy(auth_client, local_keep_last=2)
    response = auth_client.put(
        f"/api/instances/{trim}/storage-policy",
        json={"retention_override": True, "retention": {"local_keep_last": 1}},
    )
    assert response.status_code == 200
    policy = response.json()
    assert policy["effective_retention"]["local_keep_last"] == 1
    assert policy["remote_upload"] == "inherit"
    assert policy["effective_upload"] is False

    inherited = auth_client.get(f"/api/instances/{keep}/storage-policy").json()
    assert inherited["retention_override"] is False
    assert inherited["effective_retention"]["local_keep_last"] == 2

    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    by_instance = {}
    for item in report["deleted"]:
        by_instance.setdefault(item["instance_name"], 0)
        by_instance[item["instance_name"]] += 1
    assert by_instance == {"keep": 1, "trim": 2}


def test_override_with_no_rules_keeps_everything(auth_client):
    instance_id = create_instance(auth_client)
    for age in (0, 1, 2):
        seed_success(instance_id, "shop", age)
    set_policy(auth_client, local_keep_last=1)
    auth_client.put(
        f"/api/instances/{instance_id}/storage-policy", json={"retention_override": True}
    )
    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert report["deleted"] == []


def test_runs_of_deleted_instance_use_global_policy(auth_client):
    instance_id = create_instance(auth_client, name="gone")
    paths = [seed_success(instance_id, "shop", age, name="gone")[1] for age in (0, 1, 2)]
    auth_client.delete(f"/api/instances/{instance_id}")
    set_policy(auth_client, local_keep_last=2)
    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert len(report["deleted"]) == 1
    assert [p.exists() for p in paths] == [True, True, False]


def test_failed_and_active_runs_are_never_touched(auth_client):
    instance_id = create_instance(auth_client)
    seed_success(instance_id, "shop", 0)
    with get_sessionmaker()() as db:
        old = datetime.now(UTC) - timedelta(days=100)
        db.add(
            BackupRun(
                instance_id=instance_id,
                instance_name="prod",
                database_name="shop",
                trigger="single",
                status="failed",
                requested_at=old,
                finished_at=old,
                bytes_processed=0,
                error_code="dump_failed",
            )
        )
        db.commit()
    set_policy(auth_client, local_max_age_days=1, local_keep_last=1)
    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert report["deleted"] == []


def test_retention_runs_after_each_backup(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    set_policy(auth_client, local_keep_last=1)

    def backup():
        run_id = auth_client.post(
            f"/api/instances/{instance_id}/backups",
            json={"scope": "single", "database": "ok_shop"},
        ).json()["created"][0]["id"]
        return wait_for_run(auth_client, run_id)

    first = backup()
    second = backup()
    assert second["status"] == "success"
    # Retention runs right after the backup is recorded; give it a moment.
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        first = auth_client.get(f"/api/backups/runs/{first['id']}").json()
        if first["file_deleted_at"]:
            break
        time.sleep(0.05)
    assert first["file_deleted_reason"] == "retention"
    files = list(BACKUP_ROOT.rglob("*.sql.gz"))
    assert [f.name for f in files] == [second["file_name"]]


def test_service_apply_scoped_to_database(auth_client):
    instance_id = create_instance(auth_client)
    for age in (0, 1):
        seed_success(instance_id, "shop", age)
        seed_success(instance_id, "blog", age)
    set_policy(auth_client, local_keep_last=1)
    with get_sessionmaker()() as db:
        report = RetentionService(db, get_store()).apply(instance_id=instance_id, database="shop")
    assert [item.database_name for item in report.deleted] == ["shop"]


def test_manual_delete_after_retention(auth_client):
    instance_id = create_instance(auth_client)
    old_id, _ = seed_success(instance_id, "shop", 5)
    seed_success(instance_id, "shop", 0)
    set_policy(auth_client, local_keep_last=1)
    auth_client.post("/api/retention/apply", json={"dry_run": False})
    assert auth_client.delete(f"/api/backups/runs/{old_id}").status_code == 204
    assert auth_client.get(f"/api/backups/runs/{old_id}").status_code == 404
