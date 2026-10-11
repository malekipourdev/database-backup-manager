import stat
from pathlib import Path

import pytest

from mbp.backups.dump_command import ToolMissing, build_args, option_file, tool_for
from mbp.config import get_settings

PASSWORD = 'p@ss "quoted" \\ back'


def args_for(server_type, version="8.4.3"):
    return build_args(
        "/usr/local/bin/mysqldump",
        Path("/tmp/x/client.cnf"),
        host="db",
        port=3306,
        server_type=server_type,
        server_version=version,
        database="shop",
    )


def test_option_file_first_and_database_last():
    args = args_for("mysql")
    assert args[0] == "/usr/local/bin/mysqldump"
    assert args[1] == "--defaults-extra-file=/tmp/x/client.cnf"
    assert args[-1] == "shop"
    assert "--single-transaction" in args
    assert "--routines" in args and "--triggers" in args and "--events" in args
    assert "--no-tablespaces" in args
    assert "--protocol=TCP" in args
    assert not any("password" in a for a in args)


def test_mysql_specific_options():
    assert "--set-gtid-purged=OFF" in args_for("mysql")
    assert "--column-statistics=0" not in args_for("mysql", "8.0.36")
    assert "--column-statistics=0" in args_for("mysql", "5.7.44")


def test_mariadb_options():
    args = args_for("mariadb", "11.8.2")
    assert "--set-gtid-purged=OFF" not in args
    assert "--column-statistics=0" not in args


def test_option_file_permissions_escaping_and_cleanup():
    with option_file("backup", PASSWORD) as path:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        content = path.read_text(encoding="utf-8")
        assert content == ('[client]\nuser="backup"\npassword="p@ss \\"quoted\\" \\\\ back"\n')
        directory = path.parent
    assert not directory.exists()


def test_option_file_removed_on_error():
    with pytest.raises(RuntimeError), option_file("u", "p") as path:
        directory = path.parent
        raise RuntimeError
    assert not directory.exists()


def test_tool_for_selects_by_server_type(tmp_path):
    settings = get_settings().model_copy()
    mysql_tool = tmp_path / "mysqldump"
    maria_tool = tmp_path / "mariadb-dump"
    for tool in (mysql_tool, maria_tool):
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    settings.mysqldump_path = str(mysql_tool)
    settings.mariadb_dump_path = str(maria_tool)
    assert tool_for("mysql", settings) == str(mysql_tool)
    assert tool_for("mariadb", settings) == str(maria_tool)

    settings.mariadb_dump_path = str(tmp_path / "missing")
    with pytest.raises(ToolMissing):
        tool_for("mariadb", settings)
