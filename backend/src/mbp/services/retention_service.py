"""Retention: deletes old backup files (local and remote) per database, keeping the newest."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from mbp.backups.remote import RemoteError, RemoteStorage
from mbp.backups.store import LocalBackupStore
from mbp.db import utcnow
from mbp.models import BackupRun, DbInstance
from mbp.repositories.backup_run_repository import BackupRunRepository
from mbp.repositories.backup_settings_repository import BackupSettingsRepository
from mbp.services.remote_storage_service import get_remote_storage

logger = logging.getLogger(__name__)

# Retention runs after every backup and on a timer; one pass at a time keeps it simple.
_LOCK = threading.Lock()


@dataclass(frozen=True)
class RetentionPolicy:
    """NULL rules are off. A backup is expired if it breaks any rule that is on."""

    keep_last: int | None = None
    max_age_days: int | None = None

    @property
    def active(self) -> bool:
        return self.keep_last is not None or self.max_age_days is not None


@dataclass(frozen=True)
class EffectiveRetention:
    local: RetentionPolicy
    remote: RetentionPolicy


def global_retention(db: Session) -> EffectiveRetention:
    row = BackupSettingsRepository(db).get()
    return EffectiveRetention(
        local=RetentionPolicy(row.local_keep_last, row.local_max_age_days),
        remote=RetentionPolicy(row.remote_keep_last, row.remote_max_age_days),
    )


def instance_retention(instance: DbInstance) -> EffectiveRetention:
    return EffectiveRetention(
        local=RetentionPolicy(
            instance.retention_local_keep_last, instance.retention_local_max_age_days
        ),
        remote=RetentionPolicy(
            instance.retention_remote_keep_last, instance.retention_remote_max_age_days
        ),
    )


def effective_retention(db: Session, instance: DbInstance | None) -> EffectiveRetention:
    """The instance's own policy when it overrides, otherwise the global policy."""
    if instance is not None and instance.retention_override:
        return instance_retention(instance)
    return global_retention(db)


def expired(runs: list[BackupRun], policy: RetentionPolicy, now: datetime) -> list[BackupRun]:
    """Runs (given newest first) that the policy deletes. The newest one is always kept."""
    if not policy.active:
        return []
    cutoff = now - timedelta(days=policy.max_age_days) if policy.max_age_days else None
    result = []
    for index, run in enumerate(runs):
        if index == 0:
            continue
        too_many = policy.keep_last is not None and index >= policy.keep_last
        finished = run.finished_at or run.requested_at
        too_old = cutoff is not None and finished < cutoff
        if too_many or too_old:
            result.append(run)
    return result


@dataclass
class RetentionItem:
    run_id: int
    target: str  # local | remote
    instance_name: str
    database_name: str
    file_name: str | None
    finished_at: datetime | None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class RetentionReport:
    dry_run: bool
    deleted: list[RetentionItem] = field(default_factory=list)
    errors: list[RetentionItem] = field(default_factory=list)


def _item(run: BackupRun, target: str) -> RetentionItem:
    return RetentionItem(
        run_id=run.id,
        target=target,
        instance_name=run.instance_name,
        database_name=run.database_name,
        file_name=PurePosixPath(run.file_path).name if run.file_path else None,
        finished_at=run.finished_at,
    )


RemoteFactory = Callable[[Session], tuple[object, RemoteStorage | None]]


class RetentionService:
    def __init__(
        self,
        db: Session,
        store: LocalBackupStore,
        remote_factory: RemoteFactory = get_remote_storage,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = db
        self.store = store
        self.remote_factory = remote_factory
        self.clock = clock
        self.runs = BackupRunRepository(db)

    def apply(
        self,
        *,
        instance_id: int | None = None,
        database: str | None = None,
        dry_run: bool = False,
    ) -> RetentionReport:
        """Apply retention to every database (or one instance/database) and report it."""
        with _LOCK:
            return self._apply(instance_id, database, dry_run)

    def _apply(
        self, instance_id: int | None, database: str | None, dry_run: bool
    ) -> RetentionReport:
        report = RetentionReport(dry_run=dry_run)
        now = self.clock()
        candidates = self.runs.list_retention_candidates(instance_id, database)
        groups: dict[tuple, list[BackupRun]] = {}
        for run in candidates:
            # Runs of a deleted instance keep their name, so they still form a group.
            key = (
                run.instance_id,
                run.instance_name if run.instance_id is None else "",
                run.database_name,
            )
            groups.setdefault(key, []).append(run)

        policies: dict[int | None, EffectiveRetention] = {}
        remote: RemoteStorage | None = None
        remote_loaded = False

        for (group_instance_id, _, _), runs in groups.items():
            if group_instance_id not in policies:
                instance = self.db.get(DbInstance, group_instance_id) if group_instance_id else None
                policies[group_instance_id] = effective_retention(self.db, instance)
            policy = policies[group_instance_id]

            local_runs = [run for run in runs if run.has_local_file]
            for run in expired(local_runs, policy.local, now):
                item = _item(run, "local")
                if not dry_run:
                    self.store.delete(run.file_path)
                    run.file_deleted_at = now
                    run.file_deleted_reason = "retention"
                    logger.info(
                        "Retention deleted local backup of %s/%s (run %s): %s",
                        run.instance_name,
                        run.database_name,
                        run.id,
                        run.file_path,
                    )
                report.deleted.append(item)

            remote_runs = [run for run in runs if run.has_remote_copy]
            to_delete = expired(remote_runs, policy.remote, now)
            if to_delete and not remote_loaded:
                _, remote = self.remote_factory(self.db)
                remote_loaded = True
            for run in to_delete:
                item = _item(run, "remote")
                if dry_run:
                    report.deleted.append(item)
                    continue
                if remote is None:
                    item.error_code = "remote_not_configured"
                    report.errors.append(item)
                    continue
                try:
                    remote.delete(run.remote_key or "")
                except RemoteError as exc:
                    item.error_code = exc.code
                    item.error_message = exc.message
                    run.remote_error = f"Retention could not delete the remote copy: {exc.code}"
                    report.errors.append(item)
                    logger.warning("Retention could not delete remote copy of run %s", run.id)
                    continue
                run.remote_status = "deleted"
                run.remote_deleted_at = now
                logger.info(
                    "Retention deleted remote backup of %s/%s (run %s): %s",
                    run.instance_name,
                    run.database_name,
                    run.id,
                    run.remote_key,
                )
                report.deleted.append(item)
            if not dry_run:
                self.db.commit()
        if dry_run:
            self.db.rollback()
        return report
