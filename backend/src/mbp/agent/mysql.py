"""Database work an agent does for the panel on its own server: test, list and dump.

The panel sends the connection details (over the agent's TLS connection) with every call;
the agent stores nothing. Dumps run with the same tool options as the panel's own, and the
dump is streamed back as it is produced (see mbp.backups.frames).
"""

import contextlib
import ipaddress
import logging
import os
import signal
import subprocess
import tempfile
from collections.abc import AsyncIterator

import anyio
from pydantic import BaseModel, Field, SecretStr

from mbp.agent.docker import REF_RE, DockerClient, DockerError
from mbp.backups import dump_command, frames
from mbp.backups.pipeline import STDERR_TAIL_BYTES
from mbp.logging import register_secret
from mbp.services import mysql_probe
from mbp.services.mysql_probe import ConnParams

logger = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024


class MysqlTarget(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(max_length=1024)


class DumpRequest(MysqlTarget):
    database: str = Field(min_length=1, max_length=64)
    server_type: str | None = Field(default=None, max_length=16)
    server_version: str | None = Field(default=None, max_length=64)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def resolve_host(docker: DockerClient, host: str) -> str:
    """A container's name stands for its IP address; anything else is used as it is."""
    if host == "localhost" or _is_ip(host) or not REF_RE.fullmatch(host):
        return host
    try:
        inspect = docker.inspect(host)
    except DockerError:
        return host
    networks = ((inspect.get("NetworkSettings") or {}).get("Networks")) or {}
    for network in networks.values():
        address = (network or {}).get("IPAddress")
        if address:
            return address
    return host


def params_of(docker: DockerClient, target: MysqlTarget) -> ConnParams:
    password = target.password.get_secret_value()
    register_secret(password)
    return ConnParams(
        host=resolve_host(docker, target.host),
        port=target.port,
        username=target.username,
        password=password,
    )


def test(docker: DockerClient, target: MysqlTarget, timeout: int) -> dict:
    result = mysql_probe.test_connection(params_of(docker, target), timeout)
    return {
        "ok": result.ok,
        "tested_at": result.tested_at.isoformat(),
        "server_type": result.server_type,
        "server_version": result.server_version,
        "error_code": result.error_code,
        "error_detail": result.error_detail,
    }


def databases(docker: DockerClient, target: MysqlTarget, timeout: int) -> dict:
    result = mysql_probe.list_databases(params_of(docker, target), timeout)
    return {
        "ok": result.ok,
        "names": result.names,
        "error_code": result.error_code,
        "error_detail": result.error_detail,
    }


def tool_path(server_type: str | None, mysqldump: str, mariadb_dump: str) -> str:
    path = mariadb_dump if server_type == "mariadb" else mysqldump
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        raise DockerError("tool_missing", 500, f"Dump tool not found: {path}")
    return path


def _kill(process: subprocess.Popen) -> None:
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


async def dump_stream(tool: str, params: ConnParams, body: DumpRequest) -> AsyncIterator[bytes]:
    """The dump as frames. Stopping the iteration (the panel went away) kills the tool."""
    with dump_command.option_file(params.username, params.password) as cnf:
        args = dump_command.build_args(
            tool,
            cnf,
            host=params.host,
            port=params.port,
            server_type=body.server_type,
            server_version=body.server_version,
            database=body.database,
        )
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(cnf.parent)}
        with tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                args,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
            stdout = process.stdout
            assert stdout is not None  # noqa: S101 - stdout=PIPE above
            try:
                while chunk := await anyio.to_thread.run_sync(stdout.read1, CHUNK_SIZE):
                    yield frames.encode(frames.DATA, chunk)
                returncode = await anyio.to_thread.run_sync(process.wait)
                stderr_file.seek(0, os.SEEK_END)
                stderr_file.seek(max(0, stderr_file.tell() - STDERR_TAIL_BYTES))
                tail = stderr_file.read().decode("utf-8", errors="replace")
                yield frames.end_frame(returncode, tail)
                logger.info("Dumped %s (exit code %s)", body.database, returncode)
            finally:
                stdout.close()
                _kill(process)
