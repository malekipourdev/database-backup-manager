"""Dump tool selection, arguments and the private credentials option file."""

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mbp.config import Settings

COMMON_OPTIONS = (
    # The panel always connects over the network; "localhost" must not mean a Unix socket.
    "--protocol=TCP",
    "--single-transaction",
    "--quick",
    "--routines",
    "--triggers",
    "--events",
    "--hex-blob",
    # Avoids needing the PROCESS privilege on MySQL >= 8.0.21.
    "--no-tablespaces",
    "--default-character-set=utf8mb4",
)


class ToolMissing(Exception):
    pass


def is_safe_database_name(name: str) -> bool:
    """True if the dump tool cannot read the name as an option (no leading "-").

    The database name is the only argv element taken from user input; a value such as
    "--plugin-dir=..." would otherwise be parsed as an option by mysqldump/mariadb-dump.
    """
    return (
        0 < len(name) <= 64
        and not name.startswith("-")
        and not any(ord(ch) < 32 or ch == "\x7f" for ch in name)
    )


def tool_for(server_type: str | None, settings: Settings) -> str:
    """Absolute path of the dump tool for a server type (never resolved through PATH)."""
    path = settings.mariadb_dump_path if server_type == "mariadb" else settings.mysqldump_path
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        raise ToolMissing(path)
    return path


def _major(version: str | None) -> int:
    try:
        return int((version or "").split(".")[0])
    except ValueError:
        return 0


def build_args(
    tool: str,
    option_file: Path,
    *,
    host: str,
    port: int,
    server_type: str | None,
    server_version: str | None,
    database: str,
) -> list[str]:
    if not is_safe_database_name(database):
        raise ValueError("unsafe database name")
    # --defaults-extra-file must be the first option; the password lives only in that file.
    args = [tool, f"--defaults-extra-file={option_file}", f"--host={host}", f"--port={port}"]
    args += COMMON_OPTIONS
    if server_type != "mariadb":
        # Keeps GTID_PURGED out of the dump so it restores into any server.
        args.append("--set-gtid-purged=OFF")
        if 0 < _major(server_version) < 8:
            args.append("--column-statistics=0")
    args.append(database)
    return args


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    )
    return f'"{escaped}"'


@contextmanager
def option_file(user: str, password: str) -> Iterator[Path]:
    """A [client] option file readable only by this process user; removed on exit."""
    directory = Path(tempfile.mkdtemp(prefix="mbp-dump-"))  # created with mode 0700
    path = directory / "client.cnf"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"[client]\nuser={_quote(user)}\npassword={_quote(password)}\n")
        yield path
    finally:
        shutil.rmtree(directory, ignore_errors=True)
