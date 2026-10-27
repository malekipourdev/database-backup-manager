"""The agent's HTTP API, used only by the panel.

Local mode (the panel's own server): plain HTTP on the compose network, with a bearer token
derived from MBP_ENCRYPTION_KEY. Remote mode (MBP_AGENT_TOKEN set, another server): HTTPS
with the agent's own certificate and signed requests (see mbp.security.agent_auth).
"""

import hmac
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mbp.agent import PROTOCOL, mysql
from mbp.agent.deploy import DeployManager, DeploySpec
from mbp.agent.docker import (
    ACTIONS,
    COMPOSE_PROJECT,
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
from mbp.agent.hostexec import DockerHostRunner
from mbp.agent.webmanage import WebManager
from mbp.agent.webserver import scan as scan_webservers
from mbp.backups import dump_command
from mbp.security import agent_auth
from mbp.security.agent_token import agent_token

logger = logging.getLogger(__name__)


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MBP_")

    # Local mode: the token is derived from the panel's key, which this agent shares.
    encryption_key: SecretStr | None = None
    # Remote mode: the server's own token, from the panel's "add server" page. The agent
    # then serves HTTPS with a certificate kept in agent_data_dir.
    agent_token: SecretStr | None = None
    agent_data_dir: str = "/data"
    docker_host: str = "unix:///var/run/docker.sock"
    agent_bind: str = "0.0.0.0"  # noqa: S104 - reachable only on the compose network
    agent_port: int = 8090
    # Where deployed projects are checked out. Mounted at the same path as on the host, so
    # relative bind mounts in their compose files point to the right host directories.
    projects_dir: str = "/opt/mbp-projects"
    # Transports git may use (GIT_ALLOW_PROTOCOL).
    git_protocols: str = "https:ssh"
    # Dump tools for the backups of databases on this server.
    mysqldump_path: str = "/usr/local/bin/mysqldump"
    mariadb_dump_path: str = "/usr/bin/mariadb-dump"
    connect_timeout_seconds: int = 10
    # The host's filesystem as mounted in the agent (its /etc at <host_root>/etc, read-only),
    # for the web servers' configuration.
    host_root: str = "/host"
    # The image of the helper container that runs web server commands on the host; empty:
    # the agent's own image.
    host_helper_image: str = ""

    @property
    def remote(self) -> bool:
        return self.agent_token is not None and bool(self.agent_token.get_secret_value())

    def token(self) -> str:
        if self.remote:
            return self.agent_token.get_secret_value()  # type: ignore[union-attr]
        if self.encryption_key is None:
            raise RuntimeError("Set MBP_AGENT_TOKEN (another server) or MBP_ENCRYPTION_KEY")
        return agent_token(self.encryption_key.get_secret_value())


class DeployRequest(BaseModel):
    project: str = Field(max_length=40)
    repo_url: str = Field(max_length=500)
    ref: str = Field(max_length=200)
    compose_file: str = Field(default="docker-compose.yml", max_length=200)
    env: dict[str, str] = Field(default_factory=dict)
    auth_type: str = "none"
    credential: str | None = Field(default=None, max_length=20000)


class HelloRequest(BaseModel):
    nonce: str = Field(min_length=16, max_length=128)


class RemoveRequest(BaseModel):
    compose_file: str = Field(default="docker-compose.yml", max_length=200)
    down: bool = True


WebKind = Literal["nginx", "apache"]


class WebFile(BaseModel):
    path: str = Field(max_length=500)
    content: str = Field(max_length=200_000)
    sha256: str | None = Field(default=None, max_length=64)


class WebPath(BaseModel):
    path: str = Field(max_length=500)


class WebRestore(WebPath):
    backup: str = Field(max_length=32)


class WebEnabled(WebPath):
    enabled: bool


class WebMaintenance(WebPath):
    on: bool


class WebSiteSpec(BaseModel):
    template: str = Field(max_length=20)
    domains: list[str] = Field(max_length=50)
    name: str | None = Field(default=None, max_length=63)
    target: str | None = Field(default=None, max_length=300)
    root: str | None = Field(default=None, max_length=300)
    php_fpm: str | None = Field(default=None, max_length=300)
    permanent: bool = True
    keep_path: bool = True


class CertbotIssue(BaseModel):
    domains: list[str] = Field(max_length=50)
    email: str | None = Field(default=None, max_length=254)
    redirect: bool = True


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
    deployer: DeployManager | None = None,
    cert_fingerprint: str = "",
    web: WebManager | None = None,
) -> FastAPI:
    """`cert_fingerprint`: of the agent's TLS certificate, in remote mode."""
    docker = docker or DockerClient(settings.docker_host)
    host = host or HostProbe()

    def protected_projects() -> set[str]:
        """Compose projects of the panel itself: never deployed over or removed."""
        return {
            labels_of(item).get(COMPOSE_PROJECT, "")
            for item in docker.list_raw()
            if labels_of(item).get(PANEL_LABEL)
        } - {""}

    deployer = deployer or DeployManager(
        settings.projects_dir,
        protected_projects=protected_projects,
        git_protocols=settings.git_protocols,
    )
    web = web or WebManager(
        settings.host_root, DockerHostRunner(docker, settings.host_helper_image)
    )
    token = settings.token()
    remote = settings.remote
    cache = StatsCache()
    pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="mbp-agent")
    app = FastAPI(title="MBP agent", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(DockerError)
    async def _docker_error(request: Request, exc: DockerError) -> JSONResponse:
        body = {"code": exc.code}
        if exc.message:
            body["detail"] = exc.message
        return JSONResponse(status_code=exc.status, content=body)

    def require_token(request: Request, authorization: str = Header(default="")) -> None:
        if remote:
            ok = agent_auth.verify(
                authorization, token, request.method, request.url.path, cert_fingerprint
            )
            if not ok and agent_auth.clock_skewed(authorization):
                # Says nothing about the token; tells the admin to fix the server's clock.
                raise DockerError("agent_clock_skew", 401)
        else:
            scheme, _, value = authorization.partition(" ")
            ok = scheme.lower() == "bearer" and hmac.compare_digest(value, token)
        if not ok:
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

    @app.post("/v1/hello", dependencies=auth)
    def hello(body: HelloRequest) -> dict:
        """Proves to the panel that this agent holds the token and this certificate."""
        version = docker.version()
        return {
            "proof": agent_auth.proof(token, body.nonce, cert_fingerprint),
            "protocol": PROTOCOL,
            "docker_version": version.get("Version"),
            "hostname": docker.info().get("Name"),
        }

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

    @app.post("/v1/deploy", dependencies=auth)
    def deploy(body: DeployRequest) -> dict:
        job = deployer.start(DeploySpec(**body.model_dump()))
        return {"job_id": job.id}

    @app.get("/v1/deploy/{job_id}", dependencies=auth)
    def deploy_job(job_id: str, offset: int = Query(default=0, ge=0)) -> dict:
        job = deployer.get(job_id)
        if job is None:
            raise DockerError("job_not_found", 404)
        return job.view(offset)

    @app.get("/v1/projects/{name}/state", dependencies=auth)
    def project_state(name: str) -> dict:
        return deployer.state(name)

    @app.post("/v1/projects/{name}/remove", dependencies=auth)
    def project_remove(name: str, body: RemoveRequest) -> dict:
        return deployer.remove(name, body.compose_file, body.down)

    # --- web servers on this server (read-only) ---

    @app.get("/v1/webservers", dependencies=auth)
    def webservers() -> dict:
        return scan_webservers(settings.host_root)

    @app.get("/v1/webservers/status", dependencies=auth)
    def web_status() -> dict:
        return web.status()

    @app.get("/v1/webservers/certificates", dependencies=auth)
    def web_certificates() -> dict:
        return web.certificates()

    @app.get("/v1/webservers/php-sockets", dependencies=auth)
    def web_php_sockets() -> dict:
        return web.php_sockets()

    @app.get("/v1/webservers/certbot", dependencies=auth)
    def web_certbot() -> dict:
        return web.certbot()

    @app.post("/v1/webservers/certbot/renew", dependencies=auth)
    def web_certbot_renew() -> dict:
        return web.certbot_renew().view()

    @app.get("/v1/webservers/jobs/{job_id}", dependencies=auth)
    def web_job(job_id: str) -> dict:
        job = web.jobs.get(job_id)
        if job is None:
            raise DockerError("job_not_found", 404)
        return job.view()

    @app.post("/v1/webservers/{kind}/test", dependencies=auth)
    def web_test(kind: WebKind) -> dict:
        return web.test(kind)

    @app.post("/v1/webservers/{kind}/control/{action}", dependencies=auth)
    def web_control(kind: WebKind, action: Literal["reload", "restart"]) -> dict:
        return web.control(kind, action)

    @app.get("/v1/webservers/{kind}/file", dependencies=auth)
    def web_file(kind: WebKind, path: str = Query(max_length=500)) -> dict:
        return web.read_file(kind, path)

    @app.put("/v1/webservers/{kind}/file", dependencies=auth)
    def web_write(kind: WebKind, body: WebFile) -> dict:
        return web.write_file(kind, body.path, body.content, body.sha256)

    @app.get("/v1/webservers/{kind}/backups", dependencies=auth)
    def web_backups(kind: WebKind, path: str = Query(max_length=500)) -> dict:
        return web.backups(kind, path)

    @app.get("/v1/webservers/{kind}/backup", dependencies=auth)
    def web_backup(
        kind: WebKind, path: str = Query(max_length=500), backup: str = Query(max_length=32)
    ) -> dict:
        return {"content": web.read_backup(kind, path, backup)}

    @app.post("/v1/webservers/{kind}/restore", dependencies=auth)
    def web_restore(kind: WebKind, body: WebRestore) -> dict:
        return web.restore(kind, body.path, body.backup)

    @app.post("/v1/webservers/{kind}/enabled", dependencies=auth)
    def web_enabled(kind: WebKind, body: WebEnabled) -> dict:
        return web.set_enabled(kind, body.path, body.enabled)

    @app.post("/v1/webservers/{kind}/maintenance", dependencies=auth)
    def web_maintenance(kind: WebKind, body: WebMaintenance) -> dict:
        return web.set_maintenance(kind, body.path, body.on)

    @app.post("/v1/webservers/{kind}/sites", dependencies=auth)
    def web_create(kind: WebKind, body: WebSiteSpec) -> dict:
        return web.create_site(kind, body.model_dump())

    @app.get("/v1/webservers/{kind}/logs", dependencies=auth)
    def web_logs(
        kind: WebKind,
        path: str = Query(max_length=500),
        lines: int = Query(default=200, ge=1, le=2000),
    ) -> dict:
        return web.logs(kind, path, lines)

    @app.post("/v1/webservers/{kind}/certbot/issue", dependencies=auth)
    def web_certbot_issue(kind: WebKind, body: CertbotIssue) -> dict:
        return web.certbot_issue(kind, body.domains, body.email, body.redirect).view()

    @app.post("/v1/webservers/{kind}/certbot/install", dependencies=auth)
    def web_certbot_install(kind: WebKind) -> dict:
        return web.certbot_install(kind).view()

    # --- databases on this server ---

    @app.post("/v1/mysql/test", dependencies=auth)
    def mysql_test(body: mysql.MysqlTarget) -> dict:
        return mysql.test(docker, body, settings.connect_timeout_seconds)

    @app.post("/v1/mysql/databases", dependencies=auth)
    def mysql_databases(body: mysql.MysqlTarget) -> dict:
        return mysql.databases(docker, body, settings.connect_timeout_seconds)

    @app.post("/v1/mysql/dump", dependencies=auth)
    async def mysql_dump(body: mysql.DumpRequest) -> StreamingResponse:
        if not dump_command.is_safe_database_name(body.database):
            raise DockerError("invalid_database_name", 400)
        tool = mysql.tool_path(
            body.server_type, settings.mysqldump_path, settings.mariadb_dump_path
        )
        params = await run_in_threadpool(mysql.params_of, docker, body)
        return StreamingResponse(
            mysql.dump_stream(tool, params, body), media_type="application/octet-stream"
        )

    return app
