"""Principle I: the instance password never appears in the dump process's argv or env."""

import time
from pathlib import Path

from tests.conftest import INSTANCE_PAYLOAD, create_instance, wait_for_run


def test_password_not_in_process_args_or_env(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups",
        json={"scope": "single", "database": "slow_1_db"},
    ).json()["created"][0]["id"]

    runner = auth_client.app.state.backup_runner
    deadline = time.monotonic() + 5
    while run_id not in runner.active_pids() and time.monotonic() < deadline:
        time.sleep(0.01)
    pid = runner.active_pids()[run_id]

    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode()
    environ = Path(f"/proc/{pid}/environ").read_bytes().decode()
    password = INSTANCE_PAYLOAD["password"]
    assert password not in cmdline
    assert password not in environ
    assert "MYSQL_PWD" not in environ
    option_file = next(a for a in cmdline.split("\0") if a.startswith("--defaults-extra-file="))
    option_path = Path(option_file.split("=", 1)[1])
    assert oct(option_path.stat().st_mode & 0o777) == oct(0o600)

    assert wait_for_run(auth_client, run_id)["status"] == "success"
    assert not option_path.parent.exists()
