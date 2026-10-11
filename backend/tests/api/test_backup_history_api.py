"""US4: history filtering, sorting, paging."""

import time
from datetime import timedelta

import pytest
from sqlalchemy import insert

from mbp.db import utcnow
from mbp.models import BackupRun, DbInstance
from tests.conftest import create_instance

BASE = utcnow().replace(microsecond=0) - timedelta(days=10)


def add_run(db, **fields):
    defaults = {
        "instance_name": "prod",
        "database_name": "shop",
        "trigger": "single",
        "status": "success",
        "requested_at": BASE,
        "bytes_processed": 0,
    }
    run = BackupRun(**{**defaults, **fields})
    db.add(run)
    db.commit()
    return run


@pytest.fixture
def seeded(auth_client, db):
    a = create_instance(auth_client, name="alpha")
    b = create_instance(auth_client, name="beta")
    runs = [
        add_run(
            db,
            instance_id=a,
            instance_name="alpha",
            database_name="shop",
            requested_at=BASE + timedelta(days=1),
            duration_ms=500,
            file_size=300,
        ),
        add_run(
            db,
            instance_id=a,
            instance_name="alpha",
            database_name="blog",
            status="failed",
            requested_at=BASE + timedelta(days=2),
            duration_ms=100,
        ),
        add_run(
            db,
            instance_id=b,
            instance_name="beta",
            database_name="shop",
            requested_at=BASE + timedelta(days=3),
            duration_ms=900,
            file_size=100,
        ),
        add_run(
            db,
            instance_id=b,
            instance_name="beta",
            database_name="crm",
            requested_at=BASE + timedelta(days=4),
            duration_ms=50,
            file_size=200,
        ),
    ]
    return a, b, [r.id for r in runs]


def ids(client, **params):
    response = client.get("/api/backups/runs", params=params)
    assert response.status_code == 200, response.text
    return [r["id"] for r in response.json()["items"]]


def test_default_sort_newest_first(auth_client, seeded):
    _, _, run_ids = seeded
    assert ids(auth_client) == list(reversed(run_ids))


def test_filters_combine(auth_client, seeded):
    a, b, run_ids = seeded
    assert ids(auth_client, instance_id=a) == [run_ids[1], run_ids[0]]
    assert ids(auth_client, database="shop") == [run_ids[2], run_ids[0]]
    assert ids(auth_client, status="failed") == [run_ids[1]]
    assert ids(auth_client, status=["failed", "success"], instance_id=b) == [run_ids[3], run_ids[2]]
    window = {
        "from": (BASE + timedelta(days=2)).isoformat(),
        "to": (BASE + timedelta(days=4)).isoformat(),
    }
    assert ids(auth_client, **window) == [run_ids[2], run_ids[1]]


@pytest.mark.parametrize(
    ("sort", "order", "expected_index"),
    [
        ("duration_ms", "asc", [3, 1, 0, 2]),
        ("instance_name", "asc", [0, 1, 2, 3]),
        ("database_name", "desc", [2, 0, 3, 1]),
        ("status", "asc", [1, 0, 2, 3]),
        ("requested_at", "asc", [0, 1, 2, 3]),
    ],
)
def test_sorting(auth_client, seeded, sort, order, expected_index):
    _, _, run_ids = seeded
    assert ids(auth_client, sort=sort, order=order) == [run_ids[i] for i in expected_index]


def test_file_size_sort_has_all_rows(auth_client, seeded):
    assert len(ids(auth_client, sort="file_size")) == 4


def test_paging(auth_client, seeded):
    body = auth_client.get("/api/backups/runs", params={"page": 2, "page_size": 3}).json()
    assert body["total"] == 4
    assert (body["page"], body["page_size"], len(body["items"])) == (2, 3, 1)


@pytest.mark.parametrize(
    "params",
    [{"page_size": 201}, {"page": 0}, {"sort": "checksum"}, {"order": "up"}, {"status": "done"}],
)
def test_invalid_params(auth_client, params):
    response = auth_client.get("/api/backups/runs", params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_deleted_instance_runs_keep_name(auth_client, seeded, db):
    a, _, run_ids = seeded
    db.delete(db.get(DbInstance, a))
    db.commit()
    run = auth_client.get(f"/api/backups/runs/{run_ids[0]}").json()
    assert run["instance_id"] is None
    assert run["instance_name"] == "alpha"


def test_ten_thousand_runs_query_fast(auth_client, db):
    # SC-008
    rows = [
        {
            "instance_name": f"i{i % 20}",
            "database_name": f"db{i % 50}",
            "trigger": "all",
            "status": ("success", "failed")[i % 2],
            "requested_at": BASE + timedelta(minutes=i),
            "bytes_processed": 0,
            "file_size": i,
            "duration_ms": i % 997,
        }
        for i in range(10_000)
    ]
    db.execute(insert(BackupRun), rows)
    db.commit()
    started = time.monotonic()
    body = auth_client.get(
        "/api/backups/runs",
        params={"database": "db8", "status": "success", "sort": "file_size", "order": "desc"},
    ).json()
    assert time.monotonic() - started < 2
    assert body["total"] == 200
    sizes = [r["file_size"] for r in body["items"]]
    assert sizes == sorted(sizes, reverse=True)
