from sqlalchemy import select
from sqlalchemy.orm import Session

from mbp.models import BackupSchedule, DbInstance


class ScheduleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, schedule_id: int) -> BackupSchedule | None:
        return self.db.get(BackupSchedule, schedule_id)

    def list_all(self, instance_id: int | None = None, instances=None) -> list[BackupSchedule]:
        """`instances`: a condition on DbInstance (the schedules of those databases only)."""
        stmt = select(BackupSchedule).order_by(BackupSchedule.instance_id, BackupSchedule.id)
        if instance_id is not None:
            stmt = stmt.where(BackupSchedule.instance_id == instance_id)
        if instances is not None:
            stmt = stmt.where(
                BackupSchedule.instance_id.in_(select(DbInstance.id).where(instances))
            )
        return list(self.db.scalars(stmt))

    def list_enabled(self) -> list[BackupSchedule]:
        stmt = select(BackupSchedule).where(BackupSchedule.enabled.is_(True))
        return list(self.db.scalars(stmt))

    def ids_for_instance(self, instance_id: int) -> list[int]:
        stmt = select(BackupSchedule.id).where(BackupSchedule.instance_id == instance_id)
        return list(self.db.scalars(stmt))

    def add(self, schedule: BackupSchedule) -> None:
        self.db.add(schedule)
        self.db.flush()

    def delete(self, schedule: BackupSchedule) -> None:
        self.db.delete(schedule)
