"""Cron schedules and the periodic retention sweep, run by APScheduler inside the backend."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

from mbp.api.errors import ApiError
from mbp.backups.runner import BackupRunner, retention_events
from mbp.backups.store import LocalBackupStore
from mbp.config import Settings
from mbp.db import utcnow
from mbp.models import DbInstance
from mbp.notifications.events import Event
from mbp.repositories.notification_repository import NotificationRepository
from mbp.repositories.schedule_repository import ScheduleRepository
from mbp.services.backup_service import BackupService
from mbp.services.retention_service import RetentionService

logger = logging.getLogger(__name__)

RETENTION_JOB_ID = "retention-sweep"
MONITOR_JOB_ID = "alert-monitor"
SUMMARY_JOB_ID = "daily-summary"
CONTAINER_JOB_ID = "container-monitor"
WEB_JOB_ID = "web-monitor"
# Schedule results worth an alert.
PROBLEM_RESULTS = frozenset({"no_databases_selected", "instance_not_found", "error"})


def _job_id(schedule_id: int) -> str:
    return f"schedule-{schedule_id}"


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid_timezone") from exc


def build_trigger(cron: str, timezone: str) -> CronTrigger:
    """A trigger for a standard 5-field crontab expression; ValueError if invalid."""
    tz = parse_timezone(timezone)
    if len(cron.split()) != 5:
        raise ValueError("invalid_cron")
    try:
        return CronTrigger.from_crontab(cron, timezone=tz)
    except ValueError as exc:
        raise ValueError("invalid_cron") from exc


def next_fire_times(
    cron: str, timezone: str, count: int = 5, now: datetime | None = None
) -> list[datetime]:
    trigger = build_trigger(cron, timezone)
    times: list[datetime] = []
    previous = None
    current = now or datetime.now(UTC)
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, current)
        if fire is None:
            break
        times.append(fire.astimezone(UTC))
        previous = fire
        current = fire
    return times


def fire_schedule(
    schedule_id: int,
    session_factory: sessionmaker[Session],
    runner: BackupRunner,
    store: LocalBackupStore,
    *,
    force: bool = False,
) -> str | None:
    """Queue the backups of one schedule and record the outcome on it.

    `force` runs a disabled schedule too (an admin's explicit "run now").
    """
    with session_factory() as db:
        schedule = ScheduleRepository(db).get(schedule_id)
        if schedule is None or not (schedule.enabled or force):
            return None
        database = schedule.database_name if schedule.scope == "single" else None
        result, detail = "queued", None
        try:
            created, skipped = BackupService(db, runner, store).start(
                schedule.instance_id,
                schedule.scope,
                database,
                trigger="schedule",
                schedule_id=schedule.id,
            )
            if skipped and not created:
                result = "already_in_progress"
            elif skipped:
                result = "partially_queued"
            if skipped:
                detail = ", ".join(item["database"] for item in skipped)
        except ApiError as exc:
            db.rollback()
            result, detail = exc.code, exc.detail
        except Exception:
            db.rollback()
            logger.exception("Schedule %s could not queue its backups", schedule_id)
            result, detail = "error", "Unexpected internal error."
        schedule = ScheduleRepository(db).get(schedule_id)
        if schedule is None:
            return None
        schedule.last_fired_at = utcnow()
        schedule.last_result = result
        schedule.last_detail = detail
        db.commit()
        logger.info("Schedule %s fired: %s", schedule_id, result)
        return result


class BackupScheduler:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        runner: BackupRunner,
        store: LocalBackupStore,
        *,
        notifier=None,
        monitor=None,
        container_monitor=None,
        web_monitor=None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.runner = runner
        self.store = store
        self.notifier = notifier
        self.monitor = monitor
        self.container_monitor = container_monitor
        self.web_monitor = web_monitor
        self._scheduler = BackgroundScheduler(
            timezone=UTC,
            # Jobs only queue work (the runner does the dumps), so one thread is plenty.
            executors={"default": ThreadPoolExecutor(2)},
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": settings.schedule_misfire_grace_seconds,
            },
        )

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def start(self) -> None:
        self._scheduler.start()
        self.sync_all()
        if self.settings.retention_interval_minutes > 0:
            self._scheduler.add_job(
                self.run_retention,
                "interval",
                minutes=self.settings.retention_interval_minutes,
                id=RETENTION_JOB_ID,
                replace_existing=True,
            )
        if self.monitor is not None and self.settings.monitor_interval_minutes > 0:
            self._scheduler.add_job(
                self.monitor.check,
                "interval",
                minutes=self.settings.monitor_interval_minutes,
                id=MONITOR_JOB_ID,
                replace_existing=True,
            )
        if self.container_monitor is not None and self.settings.container_monitor_seconds > 0:
            self._scheduler.add_job(
                self.container_monitor.check,
                "interval",
                seconds=self.settings.container_monitor_seconds,
                id=CONTAINER_JOB_ID,
                replace_existing=True,
            )
        if self.web_monitor is not None and self.settings.web_monitor_seconds > 0:
            self._scheduler.add_job(
                self.web_monitor.check,
                "interval",
                seconds=self.settings.web_monitor_seconds,
                id=WEB_JOB_ID,
                replace_existing=True,
            )
        self.sync_daily_summary()

    def sync_daily_summary(self) -> None:
        """(Re)schedule the daily summary at the time and zone saved in the panel."""
        if self.monitor is None or not self._scheduler.running:
            return
        with self.session_factory() as db:
            settings = NotificationRepository(db).get_settings()
            hhmm, zone = settings.daily_summary_time, settings.timezone
        try:
            hour, minute = (int(part) for part in hhmm.split(":"))
            trigger = CronTrigger(hour=hour, minute=minute, timezone=parse_timezone(zone))
        except ValueError:
            logger.error("Invalid daily summary time or time zone: %s %s", hhmm, zone)
            return
        self._scheduler.add_job(
            self.monitor.send_daily_summary, trigger, id=SUMMARY_JOB_ID, replace_existing=True
        )

    def fire(self, schedule_id: int, force: bool = False) -> str | None:
        """Run a schedule (what its cron job calls, or "run now") and alert on problems."""
        result = fire_schedule(
            schedule_id, self.session_factory, self.runner, self.store, force=force
        )
        if result in PROBLEM_RESULTS and self.notifier is not None:
            with self.session_factory() as db:
                schedule = ScheduleRepository(db).get(schedule_id)
                instance = db.get(DbInstance, schedule.instance_id) if schedule else None
                params = {
                    "name": schedule.name if schedule else str(schedule_id),
                    "instance": instance.name if instance else "",
                    "result": result,
                }
            self.notifier.emit(
                Event("schedule_problem", f"schedule_problem:{schedule_id}:{result}", params)
            )
        return result

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def sync_all(self) -> None:
        """Make the scheduled jobs match the enabled schedules in the database."""
        with self.session_factory() as db:
            wanted = {s.id: (s.cron, s.timezone) for s in ScheduleRepository(db).list_enabled()}
        for job in self._scheduler.get_jobs():
            if job.id.startswith("schedule-") and int(job.id.split("-", 1)[1]) not in wanted:
                job.remove()
        for schedule_id, (cron, timezone) in wanted.items():
            self._add(schedule_id, cron, timezone)

    def sync(self, schedule_id: int) -> None:
        with self.session_factory() as db:
            schedule = ScheduleRepository(db).get(schedule_id)
            spec = (schedule.cron, schedule.timezone) if schedule and schedule.enabled else None
        if spec is None:
            self.remove(schedule_id)
        else:
            self._add(schedule_id, *spec)

    def remove(self, schedule_id: int) -> None:
        job = self._scheduler.get_job(_job_id(schedule_id))
        if job is not None:
            job.remove()

    def next_run_time(self, schedule_id: int) -> datetime | None:
        job = self._scheduler.get_job(_job_id(schedule_id))
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time.astimezone(UTC)

    def _add(self, schedule_id: int, cron: str, timezone: str) -> None:
        try:
            trigger = build_trigger(cron, timezone)
        except ValueError:
            # Validated on save; a schedule that no longer parses is skipped, not fatal.
            logger.error("Schedule %s has an invalid cron expression or time zone", schedule_id)
            self.remove(schedule_id)
            return
        self._scheduler.add_job(
            self.fire,
            trigger,
            args=[schedule_id],
            id=_job_id(schedule_id),
            replace_existing=True,
        )

    def run_retention(self) -> None:
        try:
            with self.session_factory() as db:
                report = RetentionService(db, self.store).apply()
            if self.notifier is not None:
                for event in retention_events(report):
                    self.notifier.emit(event)
            if report.deleted or report.errors:
                logger.info(
                    "Retention sweep deleted %d file(s), %d error(s)",
                    len(report.deleted),
                    len(report.errors),
                )
        except Exception:
            logger.exception("Retention sweep failed")
