"""Container and host alerts: crashes, restart loops, failing health checks, high usage.

Each condition is an AlertState while it lasts, so it is announced once and its recovery
once, across panel restarts too. Every connected server is checked; the keys of another
server than the panel's own end with "@<server id>".
"""

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from mbp.agent.docker import parse_time
from mbp.api.errors import ApiError
from mbp.containers.service import (
    ContainerService,
    ExpectedStops,
    expected_stops,
    problem,
    stop_key,
)
from mbp.db import utcnow
from mbp.models import Server
from mbp.notifications.events import Event
from mbp.repositories.container_repository import ContainerRepository
from mbp.repositories.notification_repository import NotificationRepository
from mbp.repositories.server_repository import ServerRepository
from mbp.servers.service import record_contact

logger = logging.getLogger(__name__)

AGENT_KEY = "agent:down"
HOST_KEYS = {"memory": "host:memory", "disk": "host:disk"}
# On the first check after the panel starts, only crashes this recent are announced
# (not every container that died long ago).
RECENT_CRASH = timedelta(hours=1)
# High usage must be seen this many checks in a row (a short spike is not an alert).
HIGH_USAGE_CHECKS = 2


def suffix_of(server: Server) -> str:
    """Alert keys of the panel's own server keep their single-server form."""
    return "" if server.is_local else f"@{server.id}"


def _owned(key: str, suffix: str) -> bool:
    return key.endswith(suffix) if suffix else "@" not in key


class _Server:
    """What one check needs about a server, outside the session that loaded it."""

    def __init__(self, server: Server) -> None:
        self.id = server.id
        self.name = server.name
        self.local = server.is_local
        self.suffix = suffix_of(server)
        self.row = server

    def key(self, kind: str, name: str) -> str:
        return f"container:{kind}:{name}{self.suffix}"

    def params(self) -> dict:
        return {} if self.local else {"server": self.name, "server_id": self.id}


class ContainerMonitor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        notifier,
        agents,
        *,
        clock: Callable[[], datetime] = utcnow,
        expected: ExpectedStops = expected_stops,
    ) -> None:
        self.session_factory = session_factory
        self.notifier = notifier
        # mbp.servers.registry.AgentRegistry
        self.agents = agents
        self.clock = clock
        self.expected = expected
        self._checked: set[int] = set()
        self._agent_seen: set[int] = set()
        self._restarts: dict[str, deque[tuple[datetime, int]]] = {}
        self._high: dict[str, int] = {}

    def check(self) -> list[Event]:
        try:
            events = self._check()
        except Exception:
            logger.exception("Container check failed")
            return []
        for event in events:
            self.notifier.emit(event)
        return events

    def _check(self) -> list[Event]:
        events: list[Event] = []
        with self.session_factory() as db:
            repo = ServerRepository(db)
            repo.local()
            servers = [_Server(s) for s in repo.list_all() if s.paired]
            db.expunge_all()
        for server in servers:
            try:
                events.extend(self._check_server(server))
            except Exception:
                logger.exception("Container check of server %s failed", server.name)
        return events

    def _check_server(self, server: _Server) -> list[Event]:
        now = self.clock()
        events: list[Event] = []
        agent_key = AGENT_KEY + server.suffix
        with self.session_factory() as db:
            states = NotificationRepository(db)
            try:
                agent = self.agents.for_server(server.row)
                svc = ContainerService(db, agent, server.row)
                containers = svc.containers()
            except ApiError as exc:
                record_contact(db, server.id, False, exc.code)
                active = states.active_states(agent_key)
                # Without the local agent installed the feature is simply off: no alert. Only
                # an agent that worked and then stopped answering is worth one; another
                # server's agent was set up on purpose, so it always is.
                seen = server.id in self._agent_seen or not server.local
                if seen and agent_key not in active:
                    states.activate(agent_key, now)
                    events.append(
                        Event(
                            "agent_unreachable",
                            agent_key,
                            {"code": exc.code, **server.params()},
                        )
                    )
                    db.commit()
                return events
            self._agent_seen.add(server.id)
            active = states.active_states(agent_key)
            if agent_key in active:
                states.deactivate(active[agent_key])
                events.append(Event("recovered", agent_key, {"kind": "agent", **server.params()}))
            settings = ContainerRepository(db).get_settings(server.id)
            watched = [c for c in containers if c["monitored"]]
            stats = self._stats(agent, settings, watched)
            current: set[str] = set()
            container_states = {
                key: state
                for key, state in states.active_states("container:").items()
                if _owned(key, server.suffix)
            }
            first = server.id not in self._checked
            for container in watched:
                events.extend(
                    self._container(
                        server, states, container_states, container, stats, settings, now, first
                    )
                )
                current.update(
                    server.key(k, container["name"]) for k in ("down", "loop", "health", "res")
                )
            for key, state in container_states.items():
                if key not in current:  # removed, hidden or no longer watched: forget quietly
                    states.deactivate(state)
            info = self._info(agent)
            events.extend(self._host(server, states, settings, info, now))
            db.commit()
            record_contact(db, server.id, True, None, info)
        self._checked.add(server.id)
        return events

    @staticmethod
    def _info(agent) -> dict | None:
        try:
            return agent.info()
        except ApiError:
            return None

    def _stats(self, agent, settings, watched: list[dict]) -> dict:
        if not (settings.cpu_percent or settings.memory_percent):
            return {}
        if not any(c["state"] == "running" for c in watched):
            return {}
        try:
            return agent.stats()
        except ApiError:
            return {}

    def _container(
        self, server: _Server, states, active, c: dict, stats: dict, settings, now, first: bool
    ) -> list[Event]:
        name = c["name"]
        base = {"name": name, "project": c.get("project"), **server.params()}
        events: list[Event] = []
        ident = stop_key(server.id, name)

        def _key(kind: str, name: str) -> str:
            return server.key(kind, name)

        def turn(kind: str, on: bool, event: Event | None, recovered_kind: str) -> None:
            key = _key(kind, name)
            if on and key not in active:
                states.activate(key, now)
                if event is not None:
                    events.append(event)
            elif not on and key in active:
                states.deactivate(active.pop(key))
                events.append(Event("recovered", key, {**base, "kind": recovered_kind}))

        # Crashed (exited with an error or killed for memory), unless the panel stopped it.
        crashed = problem(c) == "crashed" and not self.expected.expected(ident)
        if crashed or c["state"] == "running":
            announce = crashed
            if crashed and first:
                finished = parse_time(c.get("finished_at"))
                announce = finished is not None and now - finished <= RECENT_CRASH
            event = Event(
                "container_down",
                _key("down", name),
                {**base, "exit_code": c.get("exit_code"), "oom": bool(c.get("oom_killed"))},
            )
            turn("down", crashed, event if announce else None, "container_down")

        # Restart loop: the restart policy restarted it N times within the window.
        window = timedelta(minutes=settings.restart_window_minutes)
        history = self._restarts.setdefault(ident, deque())
        history.append((now, int(c.get("restart_count") or 0)))
        while history and now - history[0][0] > window:
            history.popleft()
        restarts = history[-1][1] - history[0][1]
        if settings.restart_count:
            looping = restarts >= settings.restart_count
            key = _key("loop", name)
            if looping or (key in active and restarts == 0 and c["state"] == "running"):
                event = Event(
                    "container_restarting",
                    key,
                    {**base, "restarts": restarts, "minutes": settings.restart_window_minutes},
                )
                turn("loop", looping, event, "container_restarting")

        # Failing health check.
        if c.get("health") in ("healthy", "unhealthy"):
            unhealthy = c["health"] == "unhealthy"
            event = Event("container_unhealthy", _key("health", name), base)
            turn("health", unhealthy, event, "container_unhealthy")

        # High CPU or memory, seen on consecutive checks.
        usage = stats.get(name)
        if usage is not None and c["state"] == "running":
            cpu, memory = usage.get("cpu_percent"), usage.get("memory_percent")
            high_cpu = (
                bool(settings.cpu_percent) and cpu is not None and cpu >= settings.cpu_percent
            )
            high_mem = (
                bool(settings.memory_percent)
                and memory is not None
                and memory >= settings.memory_percent
            )
            count = self._high.get(ident, 0) + 1 if high_cpu or high_mem else 0
            self._high[ident] = count
            event = Event(
                "container_resources",
                _key("res", name),
                {
                    **base,
                    "cpu": cpu,
                    "memory_percent": memory,
                    "memory_usage": usage.get("memory_usage"),
                    "memory_limit": usage.get("memory_limit"),
                    "high_cpu": high_cpu,
                    "high_memory": high_mem,
                },
            )
            if count >= HIGH_USAGE_CHECKS or count == 0:
                turn("res", count >= HIGH_USAGE_CHECKS, event, "container_resources")
        return events

    def _host(self, server: _Server, states, settings, info: dict | None, now) -> list[Event]:
        if not (settings.host_memory_percent or settings.host_disk_percent):
            return []
        host = (info or {}).get("host")
        if not host:
            return []
        active = {
            key: state
            for key, state in states.active_states("host:").items()
            if _owned(key, server.suffix)
        }
        events: list[Event] = []
        checks = {
            "memory": (
                settings.host_memory_percent,
                host.get("memory_total"),
                host.get("memory_available"),
            ),
            "disk": (settings.host_disk_percent, host.get("disk_total"), host.get("disk_free")),
        }
        for kind, (threshold, total, free) in checks.items():
            if not threshold or not total or free is None:
                continue
            used = total - free
            percent = used * 100 / total
            key = HOST_KEYS[kind] + server.suffix
            high = percent >= threshold
            if high and key not in active:
                states.activate(key, now)
                events.append(
                    Event(
                        "host_resources",
                        key,
                        {
                            "kind": kind,
                            "percent": round(percent, 1),
                            "used": used,
                            "total": total,
                            "threshold": threshold,
                            **server.params(),
                        },
                        severity="error" if percent >= 98 else "warning",
                    )
                )
            elif not high and key in active:
                states.deactivate(active[key])
                events.append(
                    Event(
                        "recovered",
                        key,
                        {"kind": f"host_{kind}", "percent": round(percent, 1), **server.params()},
                    )
                )
        return events
