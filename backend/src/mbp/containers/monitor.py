"""Container and host alerts: crashes, restart loops, failing health checks, high usage.

Each condition is an AlertState while it lasts, so it is announced once and its recovery
once, across panel restarts too.
"""

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from mbp.agent.docker import parse_time
from mbp.api.errors import ApiError
from mbp.containers.agent_client import AgentClient
from mbp.containers.service import ContainerService, ExpectedStops, expected_stops, problem
from mbp.db import utcnow
from mbp.notifications.events import Event
from mbp.repositories.container_repository import ContainerRepository
from mbp.repositories.notification_repository import NotificationRepository

logger = logging.getLogger(__name__)

AGENT_KEY = "agent:down"
HOST_KEYS = {"memory": "host:memory", "disk": "host:disk"}
# On the first check after the panel starts, only crashes this recent are announced
# (not every container that died long ago).
RECENT_CRASH = timedelta(hours=1)
# High usage must be seen this many checks in a row (a short spike is not an alert).
HIGH_USAGE_CHECKS = 2


def _key(kind: str, name: str) -> str:
    return f"container:{kind}:{name}"


class ContainerMonitor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        notifier,
        agent: AgentClient,
        *,
        clock: Callable[[], datetime] = utcnow,
        expected: ExpectedStops = expected_stops,
    ) -> None:
        self.session_factory = session_factory
        self.notifier = notifier
        self.agent = agent
        self.clock = clock
        self.expected = expected
        self._first = True
        self._agent_seen = False
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
        now = self.clock()
        events: list[Event] = []
        with self.session_factory() as db:
            states = NotificationRepository(db)
            svc = ContainerService(db, self.agent)
            try:
                containers = svc.containers()
            except ApiError as exc:
                active = states.active_states(AGENT_KEY)
                # Without the agent installed the feature is simply off: no alert. Only an
                # agent that worked and then stopped answering is worth one.
                if self._agent_seen and AGENT_KEY not in active:
                    states.activate(AGENT_KEY, now)
                    events.append(Event("agent_unreachable", AGENT_KEY, {"code": exc.code}))
                    db.commit()
                return events
            self._agent_seen = True
            active = states.active_states(AGENT_KEY)
            if AGENT_KEY in active:
                states.deactivate(active[AGENT_KEY])
                events.append(Event("recovered", AGENT_KEY, {"kind": "agent"}))
            settings = ContainerRepository(db).get_settings()
            watched = [c for c in containers if c["monitored"]]
            stats = self._stats(settings, watched)
            current: set[str] = set()
            container_states = states.active_states("container:")
            for container in watched:
                events.extend(
                    self._container(states, container_states, container, stats, settings, now)
                )
                current.update(
                    _key(k, container["name"]) for k in ("down", "loop", "health", "res")
                )
            for key, state in container_states.items():
                if key not in current:  # removed, hidden or no longer watched: forget quietly
                    states.deactivate(state)
            events.extend(self._host(states, settings, now))
            db.commit()
        self._first = False
        return events

    def _stats(self, settings, watched: list[dict]) -> dict:
        if not (settings.cpu_percent or settings.memory_percent):
            return {}
        if not any(c["state"] == "running" for c in watched):
            return {}
        try:
            return self.agent.stats()
        except ApiError:
            return {}

    def _container(self, states, active, c: dict, stats: dict, settings, now) -> list[Event]:
        name = c["name"]
        base = {"name": name, "project": c.get("project")}
        events: list[Event] = []

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
        crashed = problem(c) == "crashed" and not self.expected.expected(name)
        if crashed or c["state"] == "running":
            announce = crashed
            if crashed and self._first:
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
        history = self._restarts.setdefault(name, deque())
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
            count = self._high.get(name, 0) + 1 if high_cpu or high_mem else 0
            self._high[name] = count
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

    def _host(self, states, settings, now) -> list[Event]:
        if not (settings.host_memory_percent or settings.host_disk_percent):
            return []
        try:
            host = self.agent.info()["host"]
        except (ApiError, KeyError):
            return []
        active = states.active_states("host:")
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
            key = HOST_KEYS[kind]
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
                        },
                        severity="error" if percent >= 98 else "warning",
                    )
                )
            elif not high and key in active:
                states.deactivate(active[key])
                events.append(
                    Event("recovered", key, {"kind": f"host_{kind}", "percent": round(percent, 1)})
                )
        return events
