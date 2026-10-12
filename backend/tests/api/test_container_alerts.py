"""Container and host alerts raised by the container monitor."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mbp.config import get_settings
from mbp.containers.monitor import ContainerMonitor
from mbp.containers.service import ExpectedStops, stop_key
from mbp.db import get_sessionmaker
from mbp.models import ContainerSettings, NotificationLog
from mbp.notifications.events import EVENTS, Event
from mbp.notifications.notifier import Notifier
from mbp.notifications.render import render
from mbp.repositories.server_repository import ServerRepository
from mbp.servers.registry import AgentRegistry


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def expected():
    return ExpectedStops()


@pytest.fixture
def local_id(db):
    return ServerRepository(db).local().id


@pytest.fixture
def monitor(agent, clock, expected):
    notifier = Notifier(get_sessionmaker(), background=False, clock=clock)
    registry = AgentRegistry(get_settings(), get_sessionmaker(), local=lambda: agent)
    return ContainerMonitor(get_sessionmaker(), notifier, registry, clock=clock, expected=expected)


def kinds(events):
    return [
        (e.type, e.params.get("kind") if "kind" in e.params else e.params.get("name"))
        for e in events
    ]


def set_settings(db, **values):
    server_id = ServerRepository(db).local().id
    row = db.get(ContainerSettings, server_id) or ContainerSettings(
        id=server_id,
        read_only=False,
        hidden=[],
        locked=[],
        monitor_all=True,
        monitored=[],
        cpu_percent=90,
        memory_percent=90,
        restart_count=3,
        restart_window_minutes=10,
        host_memory_percent=95,
        host_disk_percent=0,
        bot_logs=False,
    )
    for key, value in values.items():
        setattr(row, key, value)
    db.merge(row)
    db.commit()


@pytest.fixture(autouse=True)
def quiet_host(db):
    # The fake host uses 75% of its memory; the real disk of the test machine is unknown.
    set_settings(db)


def test_crash_alerts_once_and_recovers(monitor, docker):
    web = docker.add("web")
    assert monitor.check() == []
    web.state, web.exit_code = "exited", 1
    assert kinds(monitor.check()) == [("container_down", "web")]
    assert monitor.check() == []  # still down: no repeat
    web.state = "running"
    assert kinds(monitor.check()) == [("recovered", "container_down")]


def test_out_of_memory_is_a_crash(monitor, docker):
    docker.add("api", state="exited", exit_code=137, oom_killed=True)
    # First check after start: only recent crashes are announced (fake FinishedAt is unset).
    assert monitor.check() == []
    docker.add("job", state="running")
    monitor.check()
    docker.containers["job"].state, docker.containers["job"].oom_killed = "exited", True
    docker.containers["job"].exit_code = 137
    [event] = monitor.check()
    assert event.type == "container_down" and event.params["oom"] is True
    assert "OOM" in render(event, "en", ZoneInfo("UTC"))


def test_recent_crash_is_announced_on_the_first_check(monitor, docker, clock):
    # Docker reports nanoseconds.
    recent = (clock.now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
    old = (clock.now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
    docker.add("fresh", state="exited", exit_code=1, finished_at=recent)
    docker.add("ancient", state="exited", exit_code=1, finished_at=old)
    assert kinds(monitor.check()) == [("container_down", "fresh")]


def test_parse_docker_times():
    from mbp.agent.docker import parse_time

    parsed = parse_time("2026-10-11T22:46:35.123456789Z")
    assert parsed == datetime(2026, 10, 11, 22, 46, 35, 123456, tzinfo=UTC)
    assert parse_time("2026-10-11T22:46:35Z").tzinfo is not None
    assert parse_time("0001-01-01T00:00:00Z") is None
    assert parse_time("garbage") is None


def test_stops_by_the_panel_or_on_purpose_are_quiet(monitor, docker, expected, local_id):
    a, b = docker.add("a"), docker.add("b")
    monitor.check()
    a.state, a.exit_code = "exited", 143  # docker stop
    expected.mark(stop_key(local_id, "b"))
    b.state, b.exit_code = "exited", 137
    assert monitor.check() == []


def test_restart_loop(monitor, docker, clock):
    loop = docker.add("loop")
    monitor.check()
    for _ in range(3):
        clock.advance(minutes=1)
        loop.restart_count += 1
        events = monitor.check()
    assert kinds(events) == [("container_restarting", "loop")]
    assert events[0].params["restarts"] == 3
    clock.advance(minutes=1)
    loop.restart_count += 1
    assert monitor.check() == []  # still looping: announced once
    clock.advance(minutes=11)
    assert kinds(monitor.check()) == [("recovered", "container_restarting")]


def test_unhealthy(monitor, docker):
    api = docker.add("api", health="healthy")
    monitor.check()
    api.health = "unhealthy"
    assert kinds(monitor.check()) == [("container_unhealthy", "api")]
    api.health = "healthy"
    assert kinds(monitor.check()) == [("recovered", "container_unhealthy")]


def test_high_memory_needs_two_checks(monitor, docker, db):
    hog = docker.add("hog", memory_usage=500 * 1024 * 1024)  # ~98% of 512 MiB
    set_settings(db, cpu_percent=0)
    assert monitor.check() == []
    events = monitor.check()
    assert kinds(events) == [("container_resources", "hog")]
    assert events[0].params["high_memory"] is True
    hog.memory_usage = 10 * 1024 * 1024
    assert kinds(monitor.check()) == [("recovered", "container_resources")]


def test_host_memory_and_disk(monitor, docker, db):
    set_settings(db, host_memory_percent=70, host_disk_percent=1)
    events = monitor.check()
    assert sorted(kinds(events)) == [("host_resources", "disk"), ("host_resources", "memory")]
    memory = next(e for e in events if e.params["kind"] == "memory")
    assert memory.params["percent"] == 75.0
    set_settings(db, host_memory_percent=80, host_disk_percent=0)
    assert kinds(monitor.check()) == [("recovered", "host_memory")]


def test_hidden_and_unwatched_containers_are_ignored(monitor, docker, db):
    a, b = docker.add("secret-vault"), docker.add("web")
    set_settings(db, hidden=["secret-*"], monitor_all=False, monitored=["other"])
    monitor.check()
    a.state = b.state = "exited"
    a.exit_code = b.exit_code = 1
    assert monitor.check() == []
    set_settings(db, monitor_all=False, monitored=["web"])
    assert kinds(monitor.check()) == [("container_down", "web")]


def test_agent_alerts_only_after_it_worked(monitor, docker):
    docker.down = True  # Docker down: the agent answers, with an error
    assert monitor.check() == []
    docker.down = False
    monitor.check()
    docker.down = True
    events = monitor.check()
    assert kinds(events) == [("agent_unreachable", None)]
    assert events[0].params["code"] == "docker_unavailable"
    assert monitor.check() == []
    docker.down = False
    assert kinds(monitor.check()) == [("recovered", "agent")]


def test_alerts_are_recorded(monitor, docker, db):
    web = docker.add("web")
    monitor.check()
    web.state, web.exit_code = "exited", 2
    monitor.check()
    entry = db.query(NotificationLog).one()
    assert (entry.event, entry.severity, entry.subject) == (
        "container_down",
        "error",
        "container:down:web",
    )


@pytest.mark.parametrize("lang", ["fa", "en"])
def test_every_container_event_renders(lang):
    zone = ZoneInfo("UTC")
    samples = [
        Event("container_down", "s", {"name": "web", "exit_code": 1, "oom": False}),
        Event("container_restarting", "s", {"name": "web", "restarts": 4, "minutes": 10}),
        Event("container_unhealthy", "s", {"name": "web"}),
        Event(
            "container_resources",
            "s",
            {
                "name": "web",
                "cpu": 97.5,
                "memory_percent": 91.0,
                "memory_usage": 1024**3,
                "memory_limit": 2 * 1024**3,
            },
        ),
        Event(
            "host_resources",
            "s",
            {
                "kind": "disk",
                "percent": 93.0,
                "used": 9 * 1024**3,
                "total": 10 * 1024**3,
                "threshold": 90,
            },
        ),
        Event("agent_unreachable", "s", {"code": "agent_unreachable"}),
    ] + [
        Event("recovered", "s", {"kind": kind, "name": "web", "percent": 50})
        for kind in (
            "container_down",
            "container_restarting",
            "container_unhealthy",
            "container_resources",
            "host_memory",
            "host_disk",
            "agent",
        )
    ]
    for event in samples:
        assert event.type in EVENTS
        text = render(event, lang, zone)
        assert "event_" not in text and "{" not in text, text


def test_alerts_of_another_server_name_it():
    event = Event(
        "container_unhealthy", "container:health:web@4", {"name": "web", "server": "edge"}
    )
    assert render(event, "en", ZoneInfo("UTC")).startswith("🖥 edge: ")
    local = Event("container_unhealthy", "container:health:web", {"name": "web"})
    assert not render(local, "en", ZoneInfo("UTC")).startswith("🖥")
