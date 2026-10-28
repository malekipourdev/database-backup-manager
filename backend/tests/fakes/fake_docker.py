"""An in-memory Docker Engine API (the parts the agent uses), as an httpx transport."""

import json
import re
import struct
import threading
from dataclasses import dataclass, field

import httpx


@dataclass
class FakeContainer:
    name: str
    image: str = "nginx:1.27"
    state: str = "running"
    labels: dict = field(default_factory=dict)
    env: list = field(default_factory=lambda: ["PATH=/usr/bin", "DB_PASSWORD=Very-Secret-42"])
    health: str | None = None
    restart_count: int = 0
    exit_code: int = 0
    oom_killed: bool = False
    restart_policy: str = "unless-stopped"
    tty: bool = False
    logs: list = field(default_factory=lambda: [("stdout", "hello"), ("stderr", "oops")])
    cpu_total: int = 1_000_000
    memory_usage: int = 50 * 1024 * 1024
    memory_limit: int = 512 * 1024 * 1024
    finished_at: str = "0001-01-01T00:00:00Z"
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = (self.name.encode().hex() + "0" * 64)[:64]


class FakeDocker:
    def __init__(self) -> None:
        self.containers: dict[str, FakeContainer] = {}
        self.down = False
        self.denied = False
        self.calls: list[tuple[str, str]] = []
        self.system_cpu = 10_000_000
        # Images: `docker save` gives a fake tar of the names; `docker load` keeps what it got.
        self.saved: list[list[str]] = []
        self.loaded: list[bytes] = []
        self.lock = threading.Lock()

    def add(self, name: str, **kwargs) -> FakeContainer:
        container = FakeContainer(name=name, **kwargs)
        self.containers[name] = container
        return container

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _find(self, ref: str) -> FakeContainer | None:
        for container in self.containers.values():
            if ref in (container.name, container.id) or container.id.startswith(ref):
                return container
        return None

    def _item(self, c: FakeContainer) -> dict:
        return {
            "Id": c.id,
            "Names": [f"/{c.name}"],
            "Image": c.image,
            "State": c.state,
            "Status": "",
            "Created": 1760000000,
            "Labels": c.labels,
            "Ports": [{"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"}],
        }

    def _inspect(self, c: FakeContainer) -> dict:
        state = {
            "Status": c.state,
            "Running": c.state == "running",
            "ExitCode": c.exit_code,
            "OOMKilled": c.oom_killed,
            "StartedAt": "2026-10-11T08:00:00Z",
            "FinishedAt": c.finished_at,
        }
        if c.health:
            state["Health"] = {
                "Status": c.health,
                "FailingStreak": 3 if c.health == "unhealthy" else 0,
                "Log": [{"Output": "curl: (7) failed"}],
            }
        return {
            "Id": c.id,
            "Name": f"/{c.name}",
            "Image": "sha256:" + "ab" * 32,
            "RestartCount": c.restart_count,
            "State": state,
            "Config": {"Image": c.image, "Env": c.env, "Labels": c.labels, "Tty": c.tty},
            "HostConfig": {"RestartPolicy": {"Name": c.restart_policy}},
            "Mounts": [{"Type": "volume", "Name": "data", "Destination": "/data", "RW": True}],
            "NetworkSettings": {"Networks": {"web": {"IPAddress": "172.18.0.5"}}},
        }

    def _stats(self, c: FakeContainer) -> dict:
        with self.lock:
            self.system_cpu += 4_000_000
            c.cpu_total += 1_000_000
            return {
                "cpu_stats": {
                    "cpu_usage": {"total_usage": c.cpu_total},
                    "system_cpu_usage": self.system_cpu,
                    "online_cpus": 2,
                },
                "precpu_stats": {},
                "memory_stats": {
                    "usage": c.memory_usage + 1024,
                    "limit": c.memory_limit,
                    "stats": {"inactive_file": 1024},
                },
                "networks": {"eth0": {"rx_bytes": 1000, "tx_bytes": 2000}},
                "blkio_stats": {"io_service_bytes_recursive": [{"op": "read", "value": 4096}]},
                "pids_stats": {"current": 3},
            }

    def _logs(self, c: FakeContainer, tail: int) -> bytes:
        entries = c.logs[-tail:]
        if c.tty:
            return "".join(f"2026-10-11T08:00:00.000Z {text}\r\n" for _, text in entries).encode()
        out = bytearray()
        for stream, text in entries:
            payload = f"2026-10-11T08:00:00.000Z \x1b[32m{text}\x1b[0m\n".encode()
            out += bytes([2 if stream == "stderr" else 1, 0, 0, 0]) + struct.pack(
                ">I", len(payload)
            )
            out += payload
        return bytes(out)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused")
        if self.denied:
            raise httpx.ConnectError("[Errno 13] Permission denied")
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path == "/version":
            return httpx.Response(200, json={"Version": "27.3.1", "ApiVersion": "1.47"})
        if path == "/info":
            running = sum(1 for c in self.containers.values() if c.state == "running")
            return httpx.Response(
                200,
                json={
                    "OperatingSystem": "Ubuntu 24.04",
                    "KernelVersion": "6.8",
                    "NCPU": 4,
                    "MemTotal": 8 * 1024**3,
                    "Containers": len(self.containers),
                    "ContainersRunning": running,
                    "ContainersStopped": len(self.containers) - running,
                    "ContainersPaused": 0,
                    "Images": 5,
                    "Name": "server-1",
                },
            )
        if path == "/images/get":
            names = request.url.params.get_list("names")
            self.saved.append(names)
            # Big enough to arrive in several chunks.
            return httpx.Response(200, content=("TAR:" + ",".join(names) + "\n").encode() * 50000)
        if path == "/images/load" and method == "POST":
            import gzip

            data = gzip.decompress(request.read())
            self.loaded.append(data)
            names = data.split(b"\n", 1)[0].decode().removeprefix("TAR:").split(",")
            lines = [json.dumps({"stream": f"Loaded image: {n}\n"}) for n in names if n]
            return httpx.Response(200, content="\n".join(lines))
        if path == "/containers/json":
            return httpx.Response(200, json=[self._item(c) for c in self.containers.values()])
        match = re.fullmatch(r"/containers/([^/]+)/(json|stats|logs|start|stop|restart)", path)
        if not match:
            return httpx.Response(404, json={"message": "page not found"})
        container = self._find(match.group(1))
        if container is None:
            return httpx.Response(404, json={"message": "No such container"})
        op = match.group(2)
        if op == "json":
            return httpx.Response(200, json=self._inspect(container))
        if op == "stats":
            return httpx.Response(200, content=json.dumps(self._stats(container)))
        if op == "logs":
            tail = int(request.url.params.get("tail", "100"))
            return httpx.Response(200, content=self._logs(container, tail))
        if method != "POST":
            return httpx.Response(405)
        if op == "start":
            if container.state == "running":
                return httpx.Response(304)
            container.state = "running"
        elif op == "stop":
            if container.state != "running":
                return httpx.Response(304)
            container.state, container.exit_code = "exited", 143
        else:
            container.state = "running"
        return httpx.Response(204)


def write_proc(root) -> None:
    """A /proc with fixed host numbers: 8 GiB RAM, 2 GiB available."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "meminfo").write_text(
        "MemTotal: 8388608 kB\nMemFree: 1000 kB\nMemAvailable: 2097152 kB\n"
    )
    (root / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 100 0 100 800 0 0 0 0 0 0\n")
    (root / "loadavg").write_text("0.50 0.40 0.30 1/100 1234\n")
