"""Web alerts: sites that stop answering (health checks) and certificates about to expire.

Health checks are requested by the panel itself, like a visitor would; a site is down after
`check_failures` failed checks in a row and announced once, its recovery once. Certificates
are read through each server's agent a few times a day; each one about to expire is an
AlertState until it is renewed.
"""

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session, sessionmaker

from mbp.api.errors import ApiError
from mbp.containers.monitor import suffix_of
from mbp.db import utcnow
from mbp.models import Server, WebCheckResult
from mbp.notifications.events import Event
from mbp.repositories.notification_repository import NotificationRepository
from mbp.repositories.server_repository import ServerRepository
from mbp.repositories.webserver_repository import WebServerRepository

logger = logging.getLogger(__name__)

CERT_INTERVAL = timedelta(hours=6)
CERT_KEY = "web:cert:"
USER_AGENT = "DevOps-Manager-HealthCheck/1.0"


def cert_key(server: Server, path: str) -> str:
    digest = hashlib.sha256(path.encode()).hexdigest()[:16]
    return f"{CERT_KEY}{digest}{suffix_of(server)}"


def server_params(server: Server) -> dict:
    return {} if server.is_local else {"server": server.name, "server_id": server.id}


def probe(url: str, timeout: float, transport: httpx.BaseTransport | None = None) -> dict:
    """One request: ok (an answer below 500), the status code, the time, or the error."""
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=5,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = client.get(url)
    except httpx.TimeoutException:
        return {"ok": False, "code": None, "ms": None, "error": "timeout"}
    except httpx.ConnectError as exc:
        reason = "tls_error" if "SSL" in str(exc) or "certificate" in str(exc) else "connect_error"
        return {"ok": False, "code": None, "ms": None, "error": reason}
    except httpx.HTTPError as exc:
        return {"ok": False, "code": None, "ms": None, "error": type(exc).__name__[:60]}
    ms = int((time.monotonic() - started) * 1000)
    ok = response.status_code < 500
    return {"ok": ok, "code": response.status_code, "ms": ms, "error": None}


class WebMonitor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        notifier,
        agents,
        *,
        clock: Callable[[], datetime] = utcnow,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.notifier = notifier
        # mbp.servers.registry.AgentRegistry
        self.agents = agents
        self.clock = clock
        self.transport = transport
        self._certs_checked: dict[int, datetime] = {}
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mbp-web-check")
        self._lock = threading.Lock()

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def check(self) -> list[Event]:
        """The scheduler's tick: due health checks, and certificates when due."""
        events: list[Event] = []
        if not self._lock.acquire(blocking=False):
            return events  # the previous tick is still running
        try:
            for step in (self.run_checks, self.check_certificates):
                try:
                    events.extend(step())
                except Exception:
                    logger.exception("Web check failed")
        finally:
            self._lock.release()
        for event in events:
            self.notifier.emit(event)
        return events

    # --- health checks ---

    def run_checks(self, only: int | None = None) -> list[Event]:
        now = self.clock()
        due: list[tuple[int, str, float]] = []
        with self.session_factory() as db:
            repo = WebServerRepository(db)
            for check in repo.checks():
                if only is not None and check.id != only:
                    continue
                if only is None and not check.enabled:
                    continue
                settings = repo.get_settings(check.server_id)
                interval = timedelta(minutes=max(settings.check_interval_minutes, 1))
                last = check.last_checked_at
                if (
                    only is None
                    and last is not None
                    and now - last < interval - timedelta(seconds=5)
                ):
                    continue
                due.append((check.id, check.url, float(settings.check_timeout_seconds)))
        results = list(
            self._pool.map(lambda item: (item[0], probe(item[1], item[2], self.transport)), due)
        )
        events: list[Event] = []
        for check_id, result in results:
            event = self._record(check_id, result, now)
            if event is not None:
                events.append(event)
        return events

    def _record(self, check_id: int, result: dict, now: datetime) -> Event | None:
        with self.session_factory() as db:
            repo = WebServerRepository(db)
            check = repo.check(check_id)
            if check is None:
                return None
            server = db.get(Server, check.server_id)
            repo.add_result(
                WebCheckResult(
                    check_id=check.id,
                    checked_at=now,
                    ok=result["ok"],
                    code=result["code"],
                    ms=result["ms"],
                    error=result["error"],
                )
            )
            check.last_checked_at = now
            check.last_code = result["code"]
            check.last_ms = result["ms"]
            check.last_error = result["error"]
            threshold = max(repo.get_settings(check.server_id).check_failures, 1)
            params = {"url": check.url, **(server_params(server) if server else {})}
            event = None
            key = f"web:down:{check.id}"
            if result["ok"]:
                if check.status == "down":
                    minutes = (
                        int((now - check.down_since).total_seconds() // 60)
                        if (check.down_since)
                        else 0
                    )
                    event = Event(
                        "recovered", key, {**params, "kind": "site_down", "minutes": minutes}
                    )
                check.status = "up"
                check.failures = 0
                check.down_since = None
            else:
                check.failures += 1
                if check.failures == 1:
                    check.down_since = now
                if check.failures >= threshold and check.status != "down":
                    check.status = "down"
                    event = Event(
                        "site_down",
                        key,
                        {
                            **params,
                            "code": result["code"],
                            "error": result["error"],
                            "failures": check.failures,
                        },
                    )
            db.commit()
            return event

    # --- certificates ---

    def check_certificates(self, force: bool = False) -> list[Event]:
        now = self.clock()
        with self.session_factory() as db:
            repo = ServerRepository(db)
            repo.local()
            servers = [s for s in repo.list_all() if s.paired]
            db.expunge_all()
        events: list[Event] = []
        for server in servers:
            last = self._certs_checked.get(server.id)
            if not force and last is not None and now - last < CERT_INTERVAL:
                continue
            try:
                certificates = self.agents.for_server(server).web_certificates()
            except ApiError:
                continue  # no agent, an old one, or no web server: nothing to watch
            self._certs_checked[server.id] = now
            events.extend(self._certificates(server, certificates, now))
        return events

    def _certificates(self, server: Server, certificates: dict, now: datetime) -> list[Event]:
        events: list[Event] = []
        with self.session_factory() as db:
            days = WebServerRepository(db).get_settings(server.id).cert_warning_days
            states = NotificationRepository(db)
            active = states.active_states(CERT_KEY)
            for path, info in certificates.items():
                if not info or info.get("error") or not info.get("not_after"):
                    continue
                key = cert_key(server, path)
                left = (datetime.fromisoformat(info["not_after"]) - now).total_seconds()
                left_days = int(left // 86400)
                params = {
                    "path": path,
                    "names": (info.get("names") or [info.get("subject") or ""])[:5],
                    "days": left_days,
                    "not_after": info["not_after"],
                    **server_params(server),
                }
                expiring = days > 0 and left_days < days
                if expiring and key not in active:
                    states.activate(key, now)
                    events.append(Event("cert_expiring", key, params))
                elif not expiring and key in active:
                    states.deactivate(active[key])
                    events.append(Event("recovered", key, {**params, "kind": "cert"}))
            db.commit()
        return events
