"""US3: bounded parallelism, FIFO queueing, duplicate guard and live progress."""

import time
from concurrent.futures import ThreadPoolExecutor

from mbp.config import get_settings
from tests.conftest import create_instance, wait_for_run


def start(client, instance_id, **body):
    return client.post(f"/api/instances/{instance_id}/backups", json=body)


def test_concurrency_limit_and_fifo(auth_client, probe_ok):
    assert get_settings().backup_concurrency == 2
    instance_id = create_instance(auth_client, select=("slow_1_a", "slow_1_b", "slow_1_c"))
    created = start(auth_client, instance_id, scope="all").json()["created"]
    ids = [run["id"] for run in sorted(created, key=lambda r: r["id"])]

    max_running = 0
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        statuses = [auth_client.get(f"/api/backups/runs/{i}").json()["status"] for i in ids]
        max_running = max(max_running, statuses.count("running"))
        if all(s in ("success", "failed") for s in statuses):
            break
        time.sleep(0.05)

    runs = [wait_for_run(auth_client, i) for i in ids]
    assert all(r["status"] == "success" for r in runs)
    assert max_running == 2
    # The third run (FIFO) only started after one of the first two finished.
    first_finish = min(runs[0]["finished_at"], runs[1]["finished_at"])
    assert runs[2]["started_at"] >= first_finish


def test_parallel_duplicate_requests_create_one_run(auth_client, probe_ok):
    instance_id = create_instance(auth_client)

    def request(_):
        return start(auth_client, instance_id, scope="single", database="slow_1_db").json()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(request, range(10)))

    created = [run for body in results for run in body["created"]]
    skipped = [s for body in results for s in body["skipped"]]
    assert len(created) == 1
    assert len(skipped) == 9
    assert all(s == {"database": "slow_1_db", "reason": "already_in_progress"} for s in skipped)
    assert wait_for_run(auth_client, created[0]["id"])["status"] == "success"

    # Once finished, the same database can be backed up again.
    again = start(auth_client, instance_id, scope="single", database="slow_1_db").json()
    assert len(again["created"]) == 1
    wait_for_run(auth_client, again["created"][0]["id"])


def test_all_skips_database_already_running(auth_client, probe_ok):
    instance_id = create_instance(auth_client, select=("slow_1_a", "ok_b"))
    first = start(auth_client, instance_id, scope="single", database="slow_1_a").json()
    body = start(auth_client, instance_id, scope="all").json()
    assert [r["database_name"] for r in body["created"]] == ["ok_b"]
    assert body["skipped"] == [{"database": "slow_1_a", "reason": "already_in_progress"}]
    wait_for_run(auth_client, first["created"][0]["id"])
    wait_for_run(auth_client, body["created"][0]["id"])


def test_progress_is_reported_while_running(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = start(auth_client, instance_id, scope="single", database="big_300_db").json()[
        "created"
    ][0]["id"]
    seen_progress = False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = auth_client.get(f"/api/backups/runs/{run_id}").json()
        if run["status"] == "running" and run["bytes_processed"] > 0:
            assert run["elapsed_ms"] is not None
            seen_progress = True
            break
        if run["status"] in ("success", "failed"):
            break
        time.sleep(0.02)
    assert seen_progress
    assert wait_for_run(auth_client, run_id, timeout=60)["status"] == "success"


def test_history_filter_by_active_status(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = start(auth_client, instance_id, scope="single", database="slow_1_db").json()[
        "created"
    ][0]["id"]
    active = auth_client.get(
        "/api/backups/runs", params={"instance_id": instance_id, "status": ["queued", "running"]}
    ).json()
    assert [r["id"] for r in active["items"]] == [run_id]
    wait_for_run(auth_client, run_id)
