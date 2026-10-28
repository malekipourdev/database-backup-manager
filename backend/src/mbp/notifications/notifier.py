"""Raises alerts: applies the rules and cooldown, records them, and delivers in the background."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mbp.db import utcnow
from mbp.models import NotificationLog
from mbp.notifications import webhook
from mbp.notifications.events import Event, merged_rules
from mbp.repositories.notification_repository import NotificationRepository
from mbp.security import crypto

logger = logging.getLogger(__name__)


class BotBroadcaster(Protocol):
    def broadcast(self, platform: str, event: Event) -> str: ...


class EventSubscribers(Protocol):
    def dispatch(self, event: Event, created_at: datetime | None = None) -> list[int]: ...


class Notifier:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        bots: BotBroadcaster | None = None,
        *,
        background: bool = True,
        clock: Callable[[], datetime] = utcnow,
        webhook_transport=None,
    ) -> None:
        self.session_factory = session_factory
        self.bots = bots
        # The external API's webhooks (mbp.apiaccess.webhooks).
        self.webhooks: EventSubscribers | None = None
        self.clock = clock
        self.webhook_transport = webhook_transport
        self._executor = (
            ThreadPoolExecutor(max_workers=2, thread_name_prefix="mbp-notify")
            if background
            else None
        )
        self._pending = 0
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def emit(
        self, event: Event, *, channels: list[str] | None = None, wait: bool = False
    ) -> int | None:
        """Record and deliver an alert; returns its log ID (None if the rule is off).

        `channels` bypasses the rules (used by the test button); `wait` delivers before
        returning. Never raises: an alerting problem must not break what raised it.
        """
        try:
            return self._emit(event, channels, wait)
        except Exception:
            logger.exception("Could not raise alert %s", event.type)
            return None

    def _emit(self, event: Event, forced_channels: list[str] | None, wait: bool) -> int | None:
        with self.session_factory() as db:
            settings = NotificationRepository(db).get_settings()
            now = self.clock()
            suppressed = event.severity != "info" and self._in_cooldown(
                db, event.subject, now - timedelta(minutes=settings.cooldown_minutes)
            )
            if forced_channels is None:
                # The external API's webhooks choose their events themselves: the alert
                # rules don't apply to them, the cooldown does.
                if self.webhooks is not None and not suppressed:
                    self.webhooks.dispatch(event, now)
                rule = merged_rules(settings.rules).get(event.type)
                if rule is None or not rule["enabled"]:
                    return None
                targets = rule["channels"]
            else:
                targets = forced_channels
            entry = NotificationLog(
                created_at=now,
                event=event.type,
                severity=event.severity,
                subject=event.subject[:200],
                params=event.params,
                run_id=event.run_id,
                channels={},
                suppressed=suppressed,
            )
            db.add(entry)
            db.commit()
            log_id = entry.id
        if suppressed or not targets:
            return log_id
        if self._executor is None or wait:
            self._deliver(log_id, event, targets)
        else:
            with self._lock:
                self._pending += 1
            self._executor.submit(self._deliver_tracked, log_id, event, targets)
        return log_id

    @staticmethod
    def _in_cooldown(db: Session, subject: str, since: datetime) -> bool:
        stmt = (
            select(NotificationLog.id)
            .where(
                NotificationLog.subject == subject[:200],
                NotificationLog.suppressed.is_(False),
                NotificationLog.created_at >= since,
            )
            .limit(1)
        )
        return db.scalar(stmt) is not None

    def _deliver_tracked(self, log_id: int, event: Event, targets: list[str]) -> None:
        try:
            self._deliver(log_id, event, targets)
        finally:
            with self._lock:
                self._pending -= 1
                self._idle.notify_all()

    def wait_idle(self, timeout: float = 10.0) -> None:
        """Wait until queued deliveries finished (tests and shutdown)."""
        with self._lock:
            self._idle.wait_for(lambda: self._pending == 0, timeout=timeout)

    def _deliver(self, log_id: int, event: Event, targets: list[str]) -> None:
        results: dict[str, str] = {}
        for channel in targets:
            try:
                results[channel] = self._send(channel, event, log_id)
            except Exception as exc:  # one channel failing must not stop the others
                logger.exception("Alert delivery via %s failed", channel)
                results[channel] = f"failed: {type(exc).__name__}"
        with self.session_factory() as db:
            entry = db.get(NotificationLog, log_id)
            if entry is not None:
                entry.channels = results
                db.commit()

    def _send(self, channel: str, event: Event, log_id: int) -> str:
        if channel == "webhook":
            with self.session_factory() as db:
                settings = NotificationRepository(db).get_settings()
                url = settings.webhook_url
                enabled = settings.webhook_enabled
                secret = (
                    crypto.decrypt(settings.webhook_secret_encrypted)
                    if settings.webhook_secret_encrypted
                    else None
                )
                entry = db.get(NotificationLog, log_id)
                created = entry.created_at.isoformat() if entry else self.clock().isoformat()
            if not enabled or not url:
                return "not_configured"
            return webhook.send(
                url, secret, webhook.payload(event, created), transport=self.webhook_transport
            )
        if self.bots is None:
            return "not_configured"
        return self.bots.broadcast(channel, event)
