"""Condition alerts (stale backups, low disk space) and the daily summary."""

import logging
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from mbp.db import utcnow
from mbp.models import BackupRun, DbInstance, DbSelection
from mbp.notifications.events import Event
from mbp.notifications.notifier import Notifier
from mbp.repositories.notification_repository import NotificationRepository
from mbp.repositories.remote_storage_repository import RemoteStorageRepository
from mbp.services.remote_storage_service import is_configured

logger = logging.getLogger(__name__)

DISK_KEY = "disk:backups"
SUMMARY_FAILED_LIMIT = 8
LOG_RETENTION_DAYS = 90


def _last_successes(db: Session) -> dict[tuple[int, str], datetime]:
    stmt = (
        select(BackupRun.instance_id, BackupRun.database_name, func.max(BackupRun.finished_at))
        .where(BackupRun.status == "success", BackupRun.instance_id.is_not(None))
        .group_by(BackupRun.instance_id, BackupRun.database_name)
    )
    return {(row[0], row[1]): row[2] for row in db.execute(stmt)}


class AlertMonitor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        notifier: Notifier,
        backup_root: str | Path,
        *,
        clock: Callable[[], datetime] = utcnow,
        disk_usage: Callable = shutil.disk_usage,
    ) -> None:
        self.session_factory = session_factory
        self.notifier = notifier
        self.backup_root = Path(backup_root)
        self.clock = clock
        self.disk_usage = disk_usage

    def check(self) -> None:
        for check in (self.check_stale, self.check_disk):
            try:
                check()
            except Exception:
                logger.exception("Alert check %s failed", check.__name__)

    def check_stale(self) -> list[Event]:
        """Alert once when a marked database has no recent successful backup; and on recovery."""
        now = self.clock()
        events: list[Event] = []
        with self.session_factory() as db:
            repo = NotificationRepository(db)
            limit = timedelta(hours=repo.get_settings().stale_hours)
            rows = db.execute(
                select(DbSelection, DbInstance.name).join(
                    DbInstance, DbInstance.id == DbSelection.instance_id
                )
            ).all()
            last = _last_successes(db)
            states = repo.active_states("stale:")
            current: set[str] = set()
            for selection, instance_name in rows:
                key = f"stale:{selection.instance_id}:{selection.database_name}"
                current.add(key)
                last_ok = last.get((selection.instance_id, selection.database_name))
                # A newly marked database gets the full period before it counts as stale.
                baseline = last_ok or selection.created_at
                stale = now - baseline > limit
                params = {"instance": instance_name, "db": selection.database_name}
                if stale and key not in states:
                    repo.activate(key, now)
                    events.append(
                        Event(
                            "stale_backup",
                            key,
                            {
                                **params,
                                "hours": int(limit.total_seconds() // 3600),
                                "last_success": last_ok.isoformat() if last_ok else None,
                            },
                        )
                    )
                elif not stale and key in states:
                    repo.deactivate(states[key])
                    events.append(Event("recovered", key, {**params, "kind": "stale_backup"}))
            for key, state in states.items():
                if key not in current:  # unmarked or server deleted: forget quietly
                    repo.deactivate(state)
            db.commit()
        for event in events:
            self.notifier.emit(event)
        return events

    def disk(self) -> tuple[int, int] | None:
        try:
            usage = self.disk_usage(self.backup_root)
        except OSError:
            return None
        return usage.free, usage.total

    def check_disk(self) -> Event | None:
        usage = self.disk()
        if usage is None or not usage[1]:
            return None
        free, total = usage
        percent = free * 100 / total
        event = None
        with self.session_factory() as db:
            repo = NotificationRepository(db)
            threshold = repo.get_settings().disk_free_percent
            states = repo.active_states(DISK_KEY)
            low = percent < threshold
            if low and DISK_KEY not in states:
                repo.activate(DISK_KEY, self.clock())
                event = Event(
                    "disk_low",
                    DISK_KEY,
                    {"free_percent": percent, "free": free, "total": total, "threshold": threshold},
                    severity="error" if percent < threshold / 2 else "warning",
                )
            elif not low and DISK_KEY in states:
                repo.deactivate(states[DISK_KEY])
                event = Event("recovered", DISK_KEY, {"kind": "disk_low", "free": free})
            db.commit()
        if event is not None:
            self.notifier.emit(event)
        return event

    def summary(self) -> dict:
        now = self.clock()
        since = now - timedelta(days=1)
        with self.session_factory() as db:
            runs = list(
                db.scalars(
                    select(BackupRun).where(
                        BackupRun.finished_at >= since, BackupRun.status.in_(("success", "failed"))
                    )
                )
            )
            remote = RemoteStorageRepository(db).get()
            stale = len(NotificationRepository(db).active_states("stale:"))
            # The summary is a good moment to keep the alert history bounded.
            NotificationRepository(db).purge_log_before(now - timedelta(days=LOG_RETENTION_DAYS))
            db.commit()
        failed = [r for r in runs if r.status == "failed"]
        usage = self.disk()
        return {
            "ok": sum(1 for r in runs if r.status == "success"),
            "failed": len(failed),
            "failed_list": [f"{r.instance_name}/{r.database_name}" for r in failed][
                :SUMMARY_FAILED_LIMIT
            ],
            "remote_enabled": is_configured(remote) and remote.enabled,
            "uploaded": sum(1 for r in runs if r.remote_status in ("success", "deleted")),
            "upload_failed": sum(1 for r in runs if r.remote_status == "failed"),
            "stale": stale,
            "disk_free": usage[0] if usage else None,
            "disk_total": usage[1] if usage else None,
        }

    def send_daily_summary(self) -> None:
        try:
            day = self.clock().date().isoformat()
            self.notifier.emit(Event("daily_summary", f"daily_summary:{day}", self.summary()))
        except Exception:
            logger.exception("Daily summary failed")
