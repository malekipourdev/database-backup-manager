"""Fixed commands on the host itself, for managing its web servers.

The agent is a container without privileges. To test a web server's configuration, reload it
or write one of its files, it starts a short-lived helper container from its own image (no
download needed) with the host's PID and network namespaces and the host's / at /host. The
helper enters PID 1's mount namespace with nsenter, or where that is refused (some sandboxes,
user namespaces) changes root into /host, and runs one command there as root. This is no new
power: access to docker.sock already is root on the host. Commands are argument lists built
by the agent (mbp.agent.webmanage), never from text the panel sends; values reach shell
snippets only as positional arguments or environment variables, never inside the script.
"""

import logging
import struct
import subprocess
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from mbp.agent.docker import PANEL_LABEL, DockerClient, DockerError

logger = logging.getLogger(__name__)

HOST_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# The helper's entry point: the host's mount namespace if allowed, else a chroot into it.
# SYSTEMD_IGNORE_CHROOT lets systemctl talk to the host's systemd from the chroot.
ENTER_SH = r"""
if nsenter --target 1 --mount -- true 2>/dev/null; then
  exec nsenter --target 1 --mount -- "$@"
fi
if [ -d /host/etc ]; then
  exec chroot /host /usr/bin/env SYSTEMD_IGNORE_CHROOT=1 "$@"
fi
echo "mbp-host: cannot enter the host (nsenter refused, no /host)" >&2
exit 125
"""
HELPER_FAILED = "mbp-host:"
MAX_OUTPUT_CHARS = 200_000


@dataclass
class HostResult:
    code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def output(self) -> str:
        text = "\n".join(part.strip("\n") for part in (self.stdout, self.stderr) if part.strip())
        return text[-MAX_OUTPUT_CHARS:]


class HostRunner(Protocol):
    # Where the host's / is for the paths given to commands: "" when they run on the host.
    prefix: str

    def run(
        self, argv: list[str], *, env: dict[str, str] | None = None, timeout: float = 60
    ) -> HostResult: ...


def demux(data: bytes) -> tuple[str, str]:
    """(stdout, stderr) of Docker's multiplexed log stream."""
    out, err = bytearray(), bytearray()
    pos = 0
    while pos + 8 <= len(data):
        stream = data[pos]
        size = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        chunk = data[pos + 8 : pos + 8 + size]
        (err if stream == 2 else out).extend(chunk)
        pos += 8 + size
    return out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


class DockerHostRunner:
    prefix = ""

    def __init__(self, docker: DockerClient, image: str | None = None) -> None:
        self.docker = docker
        self.image = image or None
        self._lock = threading.Lock()

    def _image(self) -> str:
        """The agent's own image: present on the host already."""
        with self._lock:
            if self.image:
                return self.image
            for item in self.docker.list_raw():
                labels = item.get("Labels") or {}
                if labels.get(PANEL_LABEL) == "agent" and item.get("State") == "running":
                    self.image = item.get("ImageID") or item.get("Image")
                    break
            if not self.image:
                raise DockerError("host_helper_unavailable", 503)
            return self.image

    def run(
        self, argv: list[str], *, env: dict[str, str] | None = None, timeout: float = 60
    ) -> HostResult:
        variables = {"PATH": HOST_PATH, "LC_ALL": "C", **(env or {})}
        body = {
            "Image": self._image(),
            "User": "0",
            "Entrypoint": ["sh", "-c", ENTER_SH, "mbp-host"],
            "Cmd": argv,
            "Env": [f"{k}={v}" for k, v in variables.items()],
            "Labels": {PANEL_LABEL: "helper"},
            "HostConfig": {
                "Privileged": True,
                "PidMode": "host",
                "NetworkMode": "host",
                "Binds": ["/:/host"],
                "AutoRemove": False,
            },
        }
        ref = self.docker.create(body, f"mbp-host-{uuid.uuid4().hex[:10]}")
        try:
            self.docker.start(ref)
            try:
                code = self.docker.wait(ref, timeout)
            except DockerError as exc:
                if exc.code != "docker_timeout":
                    raise
                self.docker.kill(ref)
                return HostResult(124, "", f"timed out after {int(timeout)} seconds")
            stdout, stderr = demux(self.docker.output(ref))
            if code == 125 and stderr.startswith(HELPER_FAILED):
                raise DockerError("host_helper_failed", 503, stderr.strip()[:300])
            return HostResult(code, stdout, stderr)
        finally:
            try:
                self.docker.remove(ref)
            except DockerError:
                logger.warning("Could not remove helper container %s", ref[:12])


class LocalRunner:
    """Runs commands in this machine with host paths under `prefix` (tests, development)."""

    def __init__(self, prefix: str, path: str | None = None) -> None:
        self.prefix = prefix.rstrip("/")
        self.path = path

    def run(
        self, argv: list[str], *, env: dict[str, str] | None = None, timeout: float = 60
    ) -> HostResult:
        variables = {"PATH": self.path or HOST_PATH, "LC_ALL": "C", "MBP_ROOT": self.prefix}
        variables.update(env or {})
        try:
            done = subprocess.run(  # noqa: S603 - argument list built by the agent
                argv, env=variables, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return HostResult(124, "", f"timed out after {int(timeout)} seconds")
        except OSError as exc:
            return HostResult(127, "", str(exc))
        return HostResult(
            done.returncode,
            done.stdout.decode("utf-8", "replace"),
            done.stderr.decode("utf-8", "replace"),
        )
