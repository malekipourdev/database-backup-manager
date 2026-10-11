from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbp.db import utcnow
from mbp.models import BackupRun, DbInstance
from mbp.models.backup_run import ACTIVE_STATUSES

SORT_COLUMNS = {
    "requested_at": BackupRun.requested_at,
    "duration_ms": BackupRun.duration_ms,
    "file_size": BackupRun.file_size,
    "instance_name": BackupRun.instance_name,
    "database_name": BackupRun.database_name,
    "status": BackupRun.status,
}


@dataclass
class RunFilters:
    instance_id: int | None = None
    database: str | None = None
    statuses: list[str] | None = None
    requested_from: datetime | None = None
    requested_to: datetime | None = None


def active_key(instance_id: int, database_name: str) -> str:
    return f"{instance_id}:{database_name}"


class BackupRunRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_queued(
        self, instance: DbInstance, database_name: str, trigger: str
    ) -> BackupRun | None:
        """Create and commit a queued run; None if this database already has an active run."""
        run = BackupRun(
            instance_id=instance.id,
            instance_name=instance.name,
            database_name=database_name,
            trigger=trigger,
            status="queued",
            active_key=active_key(instance.id, database_name),
            requested_at=utcnow(),
            bytes_processed=0,
        )
        self.db.add(run)
        try:
            self.db.commit()
        except IntegrityError:
            # The unique active_key is the duplicate guard (one active run per database).
            self.db.rollback()
            return None
        return run

    def get(self, run_id: int) -> BackupRun | None:
        return self.db.get(BackupRun, run_id)

    def list_active(self) -> list[BackupRun]:
        stmt = select(BackupRun).where(BackupRun.status.in_(ACTIVE_STATUSES))
        return list(self.db.scalars(stmt))

    def mark_running(self, run: BackupRun, compression: str) -> None:
        run.status = "running"
        run.started_at = utcnow()
        run.compression = compression

    def set_server(
        self, run: BackupRun, server_type: str | None, server_version: str | None
    ) -> None:
        run.server_type = server_type
        run.server_version = server_version

    def update_progress(self, run_id: int, bytes_processed: int) -> None:
        self.db.execute(
            update(BackupRun)
            .where(BackupRun.id == run_id, BackupRun.status == "running")
            .values(bytes_processed=bytes_processed)
        )

    def _finish(self, run: BackupRun, status: str) -> None:
        now = utcnow()
        run.status = status
        run.finished_at = now
        run.active_key = None
        if run.started_at is not None:
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000)

    def finish_success(
        self,
        run: BackupRun,
        *,
        file_path: str,
        file_size: int,
        checksum: str,
        bytes_processed: int,
    ) -> None:
        self._finish(run, "success")
        run.file_path = file_path
        run.file_size = file_size
        run.checksum_sha256 = checksum
        run.bytes_processed = bytes_processed
        run.error_code = None
        run.error_message = None

    def finish_failed(self, run: BackupRun, code: str, message: str | None) -> None:
        self._finish(run, "failed")
        run.file_path = None
        run.file_size = None
        run.checksum_sha256 = None
        run.error_code = code
        run.error_message = message[:1000] if message else None

    def delete(self, run: BackupRun) -> None:
        self.db.delete(run)

    def _filtered(self, stmt: Select, filters: RunFilters) -> Select:
        if filters.instance_id is not None:
            stmt = stmt.where(BackupRun.instance_id == filters.instance_id)
        if filters.database:
            stmt = stmt.where(BackupRun.database_name == filters.database)
        if filters.statuses:
            stmt = stmt.where(BackupRun.status.in_(filters.statuses))
        if filters.requested_from is not None:
            stmt = stmt.where(BackupRun.requested_at >= filters.requested_from)
        if filters.requested_to is not None:
            stmt = stmt.where(BackupRun.requested_at < filters.requested_to)
        return stmt

    def query(
        self,
        filters: RunFilters,
        sort: str = "requested_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[BackupRun], int]:
        column = SORT_COLUMNS[sort]
        direction = column.desc() if order == "desc" else column.asc()
        tie_breaker = BackupRun.id.desc() if order == "desc" else BackupRun.id.asc()
        total = self.db.scalar(self._filtered(select(func.count()).select_from(BackupRun), filters))
        stmt = (
            self._filtered(select(BackupRun), filters)
            .order_by(direction, tie_breaker)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), total or 0
