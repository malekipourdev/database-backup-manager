"""A database name must never be parsed as a dump tool option."""

from pathlib import Path

import pytest

from mbp.backups import dump_command
from tests.conftest import create_instance

BAD_NAMES = ["--plugin-dir=/tmp/x", "-hevil", "--default-auth=evil", "a\nb"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_single_backup_rejects_option_like_names(auth_client, probe_ok, name):
    instance_id = create_instance(auth_client)
    response = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": name}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("name", BAD_NAMES)
def test_selection_rejects_option_like_names(auth_client, name):
    instance_id = create_instance(auth_client)
    response = auth_client.put(
        f"/api/instances/{instance_id}/selection", json={"databases": ["ok_shop", name]}
    )
    assert response.status_code == 422


def test_names_with_inner_dashes_are_fine(auth_client, probe_ok):
    assert dump_command.is_safe_database_name("my-shop")
    assert dump_command.is_safe_database_name("فروشگاه")
    assert not dump_command.is_safe_database_name("")
    assert not dump_command.is_safe_database_name("x" * 65)


def test_build_args_refuses_unsafe_name():
    with pytest.raises(ValueError):
        dump_command.build_args(
            "/usr/bin/mysqldump",
            Path("/tmp/x.cnf"),
            host="db",
            port=3306,
            server_type="mysql",
            server_version="8.4.0",
            database="--plugin-dir=/tmp",
        )


def test_stored_unsafe_selection_fails_safely(auth_client, probe_ok):
    # A name stored before validation existed is refused by the runner, not passed to argv.
    from tests.conftest import wait_for_run

    instance_id = create_instance(auth_client, select=("--plugin-dir=/tmp",))
    created = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "all"}
    ).json()["created"]
    run = wait_for_run(auth_client, created[0]["id"])
    assert run["status"] == "failed"
    assert run["error_code"] == "invalid_database_name"
