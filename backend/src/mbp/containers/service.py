"""Rules on top of the agent: hidden and locked containers, read-only mode, the audit log."""

import fnmatch
import logging
import threading
import time

from sqlalchemy.orm import Session

from mbp.agent.docker import ACTIONS, REF_RE
from mbp.api.errors import ApiError
from mbp.containers.agent_client import AgentClient
from mbp.db import utcnow
from mbp.models import ContainerAction, ContainerSettings, Server
from mbp.repositories.container_repository import ContainerRepository

logger = logging.getLogger(__name__)

# Exit codes of a container stopped on purpose (docker stop: SIGTERM, or 0).
CLEAN_EXIT_CODES = frozenset({0, 143})
SOURCES = ("panel", "bale", "telegram")


def matches(name: str, patterns: list[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, str(p).strip().lower()) for p in patterns if p)


def problem(container: dict) -> str | None:
    """What is wrong with a container, if anything: crashed | restarting | unhealthy."""
    state = container.get("state")
    if state == "restarting":
        return "restarting"
    if state in ("exited", "dead") and (
        container.get("oom_killed") or container.get("exit_code") not in CLEAN_EXIT_CODES
    ):
        return "crashed"
    if container.get("health") == "unhealthy":
        return "unhealthy"
    return None


class ExpectedStops:
    """Containers the panel itself just stopped or restarted, so the monitor stays quiet.

    Keyed by "server id/container name".
    """

    def __init__(self, ttl_seconds: float = 300) -> None:
        self.ttl = ttl_seconds
        self._marks: dict[str, float] = {}
        self._lock = threading.Lock()

    def mark(self, name: str) -> None:
        with self._lock:
            self._marks[name] = time.monotonic()

    def expected(self, name: str) -> bool:
        with self._lock:
            mark = self._marks.get(name)
        return mark is not None and time.monotonic() - mark < self.ttl


expected_stops = ExpectedStops()


def stop_key(server_id: int, name: str) -> str:
    return f"{server_id}/{name}"


class ContainerService:
    """One server's containers, through its agent."""

    def __init__(self, db: Session, agent: AgentClient, server: Server) -> None:
        self.db = db
        self.agent = agent
        self.server_id = server.id
        self.server_name = server.name
        self.repo = ContainerRepository(db)

    @property
    def settings(self) -> ContainerSettings:
        return self.repo.get_settings(self.server_id)

    def hidden(self, name: str) -> bool:
        return matches(name, self.settings.hidden)

    def locked(self, container: dict) -> bool:
        return bool(container.get("panel")) or matches(container["name"], self.settings.locked)

    def monitored(self, name: str) -> bool:
        settings = self.settings
        return settings.monitor_all or name in (settings.monitored or [])

    def _decorate(self, container: dict) -> dict:
        return {
            **container,
            "locked": self.locked(container),
            "monitored": self.monitored(container["name"]),
            "problem": problem(container),
        }

    def containers(self) -> list[dict]:
        return [self._decorate(c) for c in self.agent.containers() if not self.hidden(c["name"])]

    def info(self) -> dict:
        return self.agent.info()

    def stats(self) -> dict[str, dict | None]:
        return {name: s for name, s in self.agent.stats().items() if not self.hidden(name)}

    @staticmethod
    def checked(ref: str) -> str:
        if not REF_RE.fullmatch(ref):
            raise ApiError(404, "container_not_found")
        return ref

    def container(self, ref: str) -> dict:
        found = self.agent.container(self.checked(ref))
        if self.hidden(found["name"]):
            raise ApiError(404, "container_not_found")
        return self._decorate(found)

    def container_stats(self, ref: str) -> dict | None:
        self.container(ref)
        return self.agent.container_stats(ref)

    def logs(self, ref: str, tail: int) -> dict:
        found = self.container(ref)
        return self.agent.logs(found["name"], tail)

    def act(self, ref: str, action: str, *, actor: str, source: str) -> dict:
        """Start, stop or restart; every attempt is written to the audit log."""
        if action not in ACTIONS:
            raise ApiError(404, "not_found")
        name = ref
        try:
            if self.settings.read_only:
                raise ApiError(403, "containers_read_only")
            found = self.container(ref)
            name = found["name"]
            if self.locked(found):
                raise ApiError(403, "container_locked")
            if action != "start":
                expected_stops.mark(stop_key(self.server_id, name))
            result = self._decorate(self.agent.action(name, action))
        except ApiError as exc:
            self._audit(actor, source, name, action, exc.code, exc.detail)
            raise
        self._audit(actor, source, name, action, "ok", None)
        logger.info(
            "%s (%s) asked to %s container %s on %s",
            actor,
            source,
            action,
            name,
            self.server_name,
        )
        return result

    def _audit(
        self, actor: str, source: str, name: str, action: str, result: str, detail: str | None
    ) -> None:
        self.repo.add_action(
            ContainerAction(
                created_at=utcnow(),
                actor=actor[:100],
                source=source,
                server_id=self.server_id,
                server_name=self.server_name[:60],
                container=name[:128],
                action=action,
                result=result[:64],
                detail=(detail or None) and detail[:300],
            )
        )
        self.db.commit()
