"""A minimal Docker Engine API client (over the Unix socket) and response parsing."""

import errno
import re
import struct
from datetime import UTC, datetime

import httpx

# Docker container names and IDs; anything else never reaches the Docker API.
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
ACTIONS = ("start", "stop", "restart")
STOP_TIMEOUT_SECONDS = 20
MAX_LOG_LINES = 5000
MAX_LOG_BYTES = 4 * 1024 * 1024
# Containers that belong to the panel itself carry this label and cannot be controlled.
PANEL_LABEL = "mbp.role"
COMPOSE_PROJECT = "com.docker.compose.project"
COMPOSE_SERVICE = "com.docker.compose.service"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ZERO_TIME = "0001-01-01T00:00:00Z"


class DockerError(Exception):
    def __init__(self, code: str, status: int = 502, message: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.message = message


def _permission_denied(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, PermissionError) or getattr(current, "errno", None) == errno.EACCES:
            return True
        current = current.__cause__ or current.__context__
    return "Permission denied" in str(exc)


class DockerClient:
    def __init__(
        self,
        host: str = "unix:///var/run/docker.sock",
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if host.startswith("unix://"):
            transport = transport or httpx.HTTPTransport(uds=host[len("unix://") :])
            base_url = "http://docker"
        else:
            base_url = host.replace("tcp://", "http://", 1)
        self._client = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise DockerError("docker_timeout", 504) from exc
        except (httpx.TransportError, OSError) as exc:
            if _permission_denied(exc):
                raise DockerError("docker_permission_denied", 503) from exc
            raise DockerError("docker_unavailable", 503) from exc
        if response.status_code == 404:
            raise DockerError("container_not_found", 404)
        if response.status_code >= 400:
            try:
                message = str(response.json().get("message", ""))[:300]
            except ValueError:
                message = ""
            raise DockerError("docker_error", 502, message)
        return response

    # --- raw API ---

    def version(self) -> dict:
        return self._request("GET", "/version").json()

    def info(self) -> dict:
        return self._request("GET", "/info").json()

    def list_raw(self) -> list[dict]:
        return self._request("GET", "/containers/json", params={"all": "1"}).json()

    def inspect(self, ref: str) -> dict:
        return self._request("GET", f"/containers/{ref}/json").json()

    def stats_raw(self, ref: str) -> dict:
        params = {"stream": "false", "one-shot": "true"}
        return self._request("GET", f"/containers/{ref}/stats", params=params).json()

    def logs_raw(self, ref: str, tail: int) -> bytes:
        params = {"stdout": "1", "stderr": "1", "timestamps": "1", "tail": str(tail)}
        with self._client.stream("GET", f"/containers/{ref}/logs", params=params) as response:
            if response.status_code == 404:
                raise DockerError("container_not_found", 404)
            if response.status_code >= 400:
                raise DockerError("docker_error", 502)
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) >= MAX_LOG_BYTES:
                    break
            return bytes(data)

    def action(self, ref: str, action: str) -> None:
        if action not in ACTIONS:
            raise DockerError("invalid_action", 400)
        params = {} if action == "start" else {"t": str(STOP_TIMEOUT_SECONDS)}
        # Docker answers 304 when the container is already started / stopped: fine.
        self._request(
            "POST",
            f"/containers/{ref}/{action}",
            params=params,
            timeout=STOP_TIMEOUT_SECONDS + 15,
        )


# --- parsing ---


def parse_time(value: str | None) -> datetime | None:
    """Docker's RFC 3339 times, which have nanoseconds (Python reads up to microseconds)."""
    if not value or value.startswith("0001-01-01"):
        return None
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _time(value: str | None) -> str | None:
    if not value or value.startswith("0001-01-01"):
        return None
    return value


def labels_of(raw: dict) -> dict:
    return raw.get("Labels") or (raw.get("Config") or {}).get("Labels") or {}


def summarize(item: dict, inspect: dict | None) -> dict:
    """One container for the list (from /containers/json plus /containers/{id}/json)."""
    inspect = inspect or {}
    state = inspect.get("State") or {}
    labels = labels_of(item)
    names = item.get("Names") or [""]
    ports = []
    seen = set()
    for port in item.get("Ports") or []:
        key = (port.get("PrivatePort"), port.get("PublicPort"), port.get("Type"))
        if key in seen:  # the same mapping is listed once per IPv4 and IPv6
            continue
        seen.add(key)
        ports.append(
            {
                "private": port.get("PrivatePort"),
                "public": port.get("PublicPort"),
                "type": port.get("Type", "tcp"),
            }
        )
    created = item.get("Created")
    return {
        "id": str(item.get("Id", ""))[:12],
        "name": names[0].lstrip("/"),
        "image": item.get("Image", ""),
        "state": item.get("State", state.get("Status", "unknown")),
        "health": (state.get("Health") or {}).get("Status"),
        "created_at": (
            datetime.fromtimestamp(created, UTC).isoformat()
            if isinstance(created, int | float)
            else None
        ),
        "started_at": _time(state.get("StartedAt")),
        "finished_at": _time(state.get("FinishedAt")),
        "exit_code": state.get("ExitCode"),
        "oom_killed": bool(state.get("OOMKilled")),
        "restart_count": inspect.get("RestartCount", 0),
        "restart_policy": ((inspect.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name")
        or "no",
        "project": labels.get(COMPOSE_PROJECT),
        "service": labels.get(COMPOSE_SERVICE),
        "panel": labels.get(PANEL_LABEL),
        "ports": ports,
    }


def details(item: dict, inspect: dict) -> dict:
    """Everything shown for one container. Environment values are never included."""
    config = inspect.get("Config") or {}
    env_names = sorted({entry.split("=", 1)[0] for entry in config.get("Env") or [] if entry})
    mounts = [
        {
            "type": mount.get("Type"),
            "source": mount.get("Name") or mount.get("Source"),
            "destination": mount.get("Destination"),
            "read_only": not mount.get("RW", True),
        }
        for mount in inspect.get("Mounts") or []
    ]
    networks = [
        {"name": name, "ip": (net or {}).get("IPAddress") or None}
        for name, net in ((inspect.get("NetworkSettings") or {}).get("Networks") or {}).items()
    ]
    health = (inspect.get("State") or {}).get("Health") or {}
    last_check = (health.get("Log") or [None])[-1] or {}
    return {
        **summarize(item, inspect),
        "image_id": str(inspect.get("Image", "")).removeprefix("sha256:")[:12],
        "hostname": config.get("Hostname"),
        "env_names": env_names,
        "mounts": mounts,
        "networks": networks,
        "health_failing_streak": health.get("FailingStreak"),
        "health_last_output": (last_check.get("Output") or "").strip()[-500:] or None,
        "tty": bool(config.get("Tty")),
    }


def parse_stats(raw: dict, previous: dict | None) -> dict:
    """Usage numbers from one stats sample; CPU% needs the previous sample (or precpu)."""
    cpu = raw.get("cpu_stats") or {}
    total = (cpu.get("cpu_usage") or {}).get("total_usage")
    system = cpu.get("system_cpu_usage")
    online = cpu.get("online_cpus") or len((cpu.get("cpu_usage") or {}).get("percpu_usage") or [])
    pre = raw.get("precpu_stats") or {}
    pre_total = (pre.get("cpu_usage") or {}).get("total_usage")
    pre_system = pre.get("system_cpu_usage")
    if not pre_system and previous:
        pre_total, pre_system = previous.get("cpu_total"), previous.get("cpu_system")
    cpu_percent = None
    if None not in (total, system, pre_total, pre_system) and online:
        delta_cpu, delta_system = total - pre_total, system - pre_system
        if delta_system > 0 and delta_cpu >= 0:
            cpu_percent = round(delta_cpu / delta_system * online * 100, 2)
    memory = raw.get("memory_stats") or {}
    mem_stats = memory.get("stats") or {}
    usage = memory.get("usage")
    if usage is not None:
        # Page cache is reclaimable; `docker stats` leaves it out the same way.
        usage -= mem_stats.get("inactive_file", mem_stats.get("total_inactive_file", 0))
    limit = memory.get("limit")
    rx = tx = 0
    for net in (raw.get("networks") or {}).values():
        rx += net.get("rx_bytes", 0)
        tx += net.get("tx_bytes", 0)
    read = write = 0
    for entry in (raw.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []:
        op = str(entry.get("op", "")).lower()
        if op == "read":
            read += entry.get("value", 0)
        elif op == "write":
            write += entry.get("value", 0)
    return {
        "cpu_percent": cpu_percent,
        "memory_usage": max(usage, 0) if usage is not None else None,
        "memory_limit": limit,
        "memory_percent": round(usage * 100 / limit, 2) if usage is not None and limit else None,
        "net_rx": rx,
        "net_tx": tx,
        "block_read": read,
        "block_write": write,
        "pids": (raw.get("pids_stats") or {}).get("current"),
        # Kept by the agent for the next CPU% computation; not part of the API.
        "cpu_total": total,
        "cpu_system": system,
    }


def _split_line(line: str, stream: str) -> dict:
    ts, sep, text = line.partition(" ")
    if not sep or not re.match(r"\d{4}-\d\d-\d\dT", ts):
        ts, text = None, line
    return {"stream": stream, "time": ts, "text": ANSI_RE.sub("", text.rstrip("\r"))}


def parse_logs(data: bytes, tty: bool) -> list[dict]:
    """Docker's log stream: raw for TTY containers, otherwise 8-byte framed per stream."""
    lines: list[dict] = []
    if tty:
        for line in data.decode("utf-8", "replace").splitlines():
            lines.append(_split_line(line, "stdout"))
        return lines
    buffers = {"stdout": "", "stderr": ""}
    offset = 0
    while offset + 8 <= len(data):
        kind, size = data[offset], struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        chunk = data[offset + 8 : offset + 8 + size]
        offset += 8 + size
        stream = "stderr" if kind == 2 else "stdout"
        text = buffers[stream] + chunk.decode("utf-8", "replace")
        *complete, rest = text.split("\n")
        buffers[stream] = rest
        lines.extend(_split_line(line, stream) for line in complete)
    for stream, rest in buffers.items():
        if rest:
            lines.append(_split_line(rest, stream))
    # Frames of the two streams arrive in order already; keep that order.
    return lines
