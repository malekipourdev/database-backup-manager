"""Connection tests and database lists, by the panel itself or by a server's agent."""

from datetime import datetime

from mbp.api.errors import ApiError
from mbp.db import utcnow
from mbp.services import mysql_probe
from mbp.services.mysql_probe import ConnParams, ListResult, ProbeResult


def target(params: ConnParams) -> dict:
    """The connection details as the agent takes them (sent only over its TLS connection)."""
    return {
        "host": params.host,
        "port": params.port,
        "username": params.username,
        "password": params.password,
    }


def _agent(server_id: int):
    from mbp.servers.registry import get_registry

    return get_registry().get(server_id)


def test_connection(server_id: int | None, params: ConnParams) -> ProbeResult:
    if server_id is None:
        return mysql_probe.test_connection(params)
    try:
        body = _agent(server_id).mysql_test(target(params))
    except ApiError as exc:
        return ProbeResult(ok=False, tested_at=utcnow(), error_code=exc.code)
    return ProbeResult(
        ok=bool(body.get("ok")),
        tested_at=_time(body.get("tested_at")),
        server_type=body.get("server_type"),
        server_version=body.get("server_version"),
        error_code=body.get("error_code"),
        error_detail=body.get("error_detail"),
    )


# Keep pytest from collecting this function when a test module imports it.
test_connection.__test__ = False  # type: ignore[attr-defined]


def list_databases(server_id: int | None, params: ConnParams) -> ListResult:
    if server_id is None:
        return mysql_probe.list_databases(params)
    try:
        body = _agent(server_id).mysql_databases(target(params))
    except ApiError as exc:
        return ListResult(ok=False, error_code=exc.code)
    return ListResult(
        ok=bool(body.get("ok")),
        names=[str(name) for name in body.get("names") or []],
        error_code=body.get("error_code"),
        error_detail=body.get("error_detail"),
    )


def _time(value) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return utcnow()
