"""Runs the enabled bots (one long-polling thread each) and sends alerts to their admins."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from mbp.backups.store import LocalBackupStore
from mbp.bots.api import BotApi, BotApiError
from mbp.bots.handler import BotHandler, button
from mbp.bots.texts import t
from mbp.db import utcnow
from mbp.models.bot import PLATFORMS
from mbp.notifications.events import Event, level_allows
from mbp.notifications.render import render_with_icon
from mbp.repositories.bot_repository import BotRepository
from mbp.repositories.notification_repository import NotificationRepository
from mbp.services.bot_service import api_for

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 60


class BotPoller:
    """Long-polls one bot's getUpdates and hands each update to the handler."""

    def __init__(self, manager: "BotManager", platform: str, api: BotApi) -> None:
        self.manager = manager
        self.platform = platform
        self.api = api
        self.handler = BotHandler(
            platform,
            api,
            manager.session_factory,
            manager.runner,
            manager.store,
            scheduler=manager.scheduler,
            agent=manager.agent,
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"mbp-bot-{platform}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Closing the client interrupts a long poll that is waiting on the network.
        self.api.close()
        self._thread.join(timeout=2)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def _record(self, *, ok: bool, error: str | None = None, offset: int | None = None) -> None:
        with self.manager.session_factory() as db:
            row = BotRepository(db).get_settings_for_update(self.platform)
            if ok:
                row.last_ok_at = utcnow()
                row.last_error = None
            else:
                row.last_error = (error or "")[:500]
            if offset is not None:
                row.last_update_id = offset
            db.commit()

    def poll_once(self, timeout: int | None = None) -> int:
        """One getUpdates round; returns the number of updates handled."""
        with self.manager.session_factory() as db:
            offset = BotRepository(db).get_settings(self.platform).last_update_id
        kwargs = {} if timeout is None else {"timeout": timeout}
        updates = self.api.get_updates(offset, **kwargs)
        next_offset = offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = max(next_offset or 0, update_id + 1)
            self.manager.dispatch(self.handler, update)
        self._record(ok=True, offset=next_offset if updates else None)
        return len(updates)

    def _loop(self) -> None:
        backoff = 1
        try:
            # getUpdates is refused while a webhook is set on the bot (e.g. by another tool).
            self.api.call("deleteWebhook")
        except BotApiError:
            logger.debug("%s bot: deleteWebhook failed", self.platform)
        try:
            me = self.api.get_me()
            with self.manager.session_factory() as db:
                BotRepository(db).get_settings_for_update(self.platform).bot_username = me.get(
                    "username"
                )
                db.commit()
        except BotApiError as exc:
            logger.warning("%s bot: getMe failed: %s", self.platform, exc.code)
        while not self._stop.is_set():
            try:
                self.poll_once()
                backoff = 1
            except BotApiError as exc:
                if self._stop.is_set():
                    break
                detail = f"{exc.code}: {exc.message}" if exc.message else exc.code
                logger.warning("%s bot: polling failed: %s", self.platform, exc.code)
                self._record(ok=False, error=detail)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            except Exception:
                if self._stop.is_set():
                    break
                logger.exception("%s bot: polling loop error", self.platform)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)


class BotManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        runner,
        store: LocalBackupStore,
        *,
        scheduler=None,
        agent=None,
        transport=None,
        threaded: bool = True,
    ) -> None:
        self.session_factory = session_factory
        self.runner = runner
        self.store = store
        self.scheduler = scheduler
        # Returns the current Docker agent client; see mbp.bots.containers.
        self.agent = agent
        self.transport = transport
        self._pollers: dict[str, BotPoller] = {}
        self._lock = threading.Lock()
        # Slow actions (a connection test, sending a file) must not hold up other updates.
        self._executor = (
            ThreadPoolExecutor(max_workers=4, thread_name_prefix="mbp-bot-handler")
            if threaded
            else None
        )

    def dispatch(self, handler: BotHandler, update: dict) -> None:
        if self._executor is None:
            handler.handle_update(update)
        else:
            self._executor.submit(handler.handle_update, update)

    def start(self) -> None:
        for platform in PLATFORMS:
            self.reload(platform)

    def stop(self) -> None:
        with self._lock:
            pollers = list(self._pollers.values())
            self._pollers.clear()
        for poller in pollers:
            poller.stop()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _build(self, platform: str) -> BotPoller | None:
        with self.session_factory() as db:
            row = BotRepository(db).get_settings(platform)
            if not row.enabled:
                return None
            api = api_for(row, transport=self.transport)
        return BotPoller(self, platform, api) if api is not None else None

    def reload(self, platform: str, *, start_thread: bool = True) -> BotPoller | None:
        """Apply saved settings: (re)start the platform's bot, or stop it if disabled."""
        with self._lock:
            old = self._pollers.pop(platform, None)
        if old is not None:
            old.stop()
        poller = self._build(platform)
        if poller is None:
            return None
        with self._lock:
            self._pollers[platform] = poller
        if start_thread:
            poller.start()
        logger.info("%s bot started", platform)
        return poller

    def running(self, platform: str) -> bool:
        poller = self._pollers.get(platform)
        return poller is not None and poller.alive

    def poller(self, platform: str) -> BotPoller | None:
        return self._pollers.get(platform)

    def broadcast(self, platform: str, event: Event) -> str:
        """Send an alert to the platform's admins whose level allows it."""
        poller = self._pollers.get(platform)
        if poller is None:
            return "not_configured"
        with self.session_factory() as db:
            admins = [
                (a.user_id, a.language)
                for a in BotRepository(db).admins(platform)
                if a.enabled and level_allows(a.notify_level, event)
            ]
            zone_name = NotificationRepository(db).get_settings().timezone
        try:
            zone = ZoneInfo(zone_name)
        except Exception:
            zone = ZoneInfo("UTC")
        if not admins:
            return "no_recipients"
        sent, failed = 0, 0
        for user_id, language in admins:
            keyboard = None
            if event.run_id is not None:
                keyboard = [[button(t(language, "btn_view"), f"r:{event.run_id}")]]
            try:
                poller.api.send_message(user_id, render_with_icon(event, language, zone), keyboard)
                sent += 1
            except BotApiError as exc:
                failed += 1
                logger.warning("%s bot: alert to %s failed: %s", platform, user_id, exc.code)
        if failed and not sent:
            return f"failed: {failed}"
        return f"sent: {sent}" + (f", failed: {failed}" if failed else "")
