"""The agent's HTTP API, used only by the backend over the internal network."""

import hmac
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mbp.agent.docker import (
    ACTIONS,
    MAX_LOG_LINES,
    PANEL_LABEL,
    REF_RE,
    DockerClient,
    DockerError,
    details,
    labels_of,
    parse_logs,
    parse_stats,
    summarize,
)
from mbp.agent.host import HostProbe
from mbp.security.agent_token import agent_token

logger = logging.getLogger(__name__)


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MBP_")

    encryption_key: SecretStr
    docker_host: str = "unix:///var/run/docker.sock"
    agent_bind: str = "0.0.0.0"  # noqa: S104 - reachable only on the compose network
    agent_port: int = 8090


class StatsCache:
    """The previous CPU sample per container, for CPU% from one-shot stats."""

    def __init__(self) -> None:
        self._samples: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            return self._samples.get(key)

    def put(self, key: str, sample: dict) -> None:
        with self._lock:
            self._samples[key] = sample


def _public(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if k not in ("cpu_total", "cpu_system")}


def create_agent_app(
    settings: AgentSettings,
    docker: DockerClient | None = None,
    host: HostProbe | None = None,
) -> FastAPI:
    docker = docker or DockerClient(settings.docker_host)
    host = host or HostProbe()
    token = agent_token(settings.encryption_key.get_secret_value())
    cache = StatsCache()
    pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="mbp-agent")
    app = FastAPI(title="MBP agent", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(DockerError)
    async def _docker_error(request: Request, exc: DockerError) -> JSONResponse:
        body = {"code": exc.code}
        if exc.message:
            body["detail"] = exc.message
        return JSONResponse(status_code=exc.status, content=body)

    def require_token(authorization: str = Header(default="")) -> None:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(value, token):
            raise DockerError("agent_unauthorized", 401)

    def checked(ref: str) -> str:
        if not REF_RE.fullmatch(ref):
            raise DockerError("container_not_found", 404)
        return ref

    def find(ref: str) -> tuple[dict, dict]:
        """(list item, inspect) for a container name or ID."""
        inspect = docker.inspect(checked(ref))
        config = inspect.get("Config") or {}
        item = {
            "Id": inspect.get("Id", ""),
            "Names": [inspect.get("Name", "")],
            "Image": config.get("Image", ""),
            "State": (inspect.get("State") or {}).get("Status", "unknown"),
            "Labels": config.get("Labels") or {},
            "Created": None,
            "Ports": [],
        }
        for raw in docker.list_raw():
            if raw.get("Id") == inspect.get("Id"):
                item = raw
                break
        return item, inspect

    def stats_for(container_id: str) -> dict:
        stats = parse_stats(docker.stats_raw(container_id), cache.get(container_id))
        cache.put(container_id, stats)
        return stats

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    auth = [Depends(require_token)]

    @app.get("/v1/info", dependencies=auth)
    def info() -> dict:
        version = docker.version()
        raw = docker.info()
        return {
            "docker": {
                "version": version.get("Version"),
                "api_version": version.get("ApiVersion"),
                "os": raw.get("OperatingSystem"),
                "kernel": raw.get("KernelVersion"),
                "cpus": raw.get("NCPU"),
                "memory_total": raw.get("MemTotal"),
                "containers": raw.get("Containers"),
                "running": raw.get("ContainersRunning"),
                "stopped": raw.get("ContainersStopped"),
                "paused": raw.get("ContainersPaused"),
                "images": raw.get("Images"),
                "name": raw.get("Name"),
            },
            "host": host.snapshot(),
        }

    @app.get("/v1/containers", dependencies=auth)
    def containers() -> dict:
        items = docker.list_raw()

        def one(item: dict) -> dict:
            try:
                inspect = docker.inspect(item["Id"])
            except DockerError:
                inspect = None  # removed in between
            return summarize(item, inspect)

        return {"containers": list(pool.map(one, items))}

    @app.get("/v1/containers/{ref}", dependencies=auth)
    def container(ref: str) -> dict:
        item, inspect = find(ref)
        return details(item, inspect)

    @app.get("/v1/containers/{ref}/stats", dependencies=auth)
    def container_stats(ref: str) -> dict:
        _, inspect = find(ref)
        if (inspect.get("State") or {}).get("Status") != "running":
            return {"stats": None}
        return {"stats": _public(stats_for(inspect["Id"]))}

    @app.get("/v1/stats", dependencies=auth)
    def all_stats() -> dict:
        running = [item for item in docker.list_raw() if item.get("State") == "running"]

        def one(item: dict) -> tuple[str, dict | None]:
            name = (item.get("Names") or [""])[0].lstrip("/")
            try:
                return name, _public(stats_for(item["Id"]))
            except DockerError:
                return name, None

        return {"stats": dict(pool.map(one, running))}

    @app.get("/v1/containers/{ref}/logs", dependencies=auth)
    def logs(ref: str, tail: int = Query(default=200, ge=1, le=MAX_LOG_LINES)) -> dict:
        _, inspect = find(ref)
        tty = bool((inspect.get("Config") or {}).get("Tty"))
        data = docker.logs_raw(inspect["Id"], tail)
        lines = parse_logs(data, tty)
        return {"lines": lines[-tail:], "truncated": len(lines) > tail}

    @app.post("/v1/containers/{ref}/{action}", dependencies=auth)
    def control(ref: str, action: str) -> dict:
        if action not in ACTIONS:
            raise DockerError("invalid_action", 400)
        item, inspect = find(ref)
        if labels_of(item).get(PANEL_LABEL) or labels_of(inspect).get(PANEL_LABEL):
            raise DockerError("container_protected", 403)
        docker.action(inspect["Id"], action)
        logger.info("%s %s", action, inspect.get("Name", ref).lstrip("/"))
        item, inspect = find(inspect["Id"])
        return {"container": summarize(item, inspect)}

    return app
