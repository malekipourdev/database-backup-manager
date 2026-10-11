from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import ScheduleIn
from mbp.backups.scheduler import build_trigger, next_fire_times
from mbp.models import BackupSchedule
from mbp.repositories.schedule_repository import ScheduleRepository
from mbp.services.instance_service import InstanceService
from mbp.services.selection_service import NON_SELECTABLE


def validate_schedule(data: ScheduleIn) -> None:
    fields: dict[str, str] = {}
    try:
        build_trigger(data.cron, data.timezone)
    except ValueError as exc:
        field = "timezone" if str(exc) == "invalid_timezone" else "cron"
        fields[field] = str(exc)
    if data.scope == "single":
        if not data.database:
            fields["database"] = "required"
        elif data.database in NON_SELECTABLE:
            fields["database"] = "not_selectable"
    if fields:
        raise ApiError(422, "validation_error", fields=fields)


def next_run_at(schedule: BackupSchedule):
    if not schedule.enabled:
        return None
    try:
        times = next_fire_times(schedule.cron, schedule.timezone, count=1)
    except ValueError:
        return None
    return times[0] if times else None


class ScheduleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ScheduleRepository(db)

    def list_all(self, instance_id: int | None = None) -> list[BackupSchedule]:
        if instance_id is not None:
            InstanceService(self.db).get(instance_id)
        return self.repo.list_all(instance_id)

    def get(self, schedule_id: int) -> BackupSchedule:
        schedule = self.repo.get(schedule_id)
        if schedule is None:
            raise ApiError(404, "schedule_not_found")
        return schedule

    def create(self, instance_id: int, data: ScheduleIn) -> BackupSchedule:
        InstanceService(self.db).get(instance_id)
        validate_schedule(data)
        schedule = BackupSchedule(instance_id=instance_id)
        self._apply(schedule, data)
        self.repo.add(schedule)
        self.db.commit()
        return schedule

    def update(self, schedule_id: int, data: ScheduleIn) -> BackupSchedule:
        schedule = self.get(schedule_id)
        validate_schedule(data)
        self._apply(schedule, data)
        self.db.commit()
        return schedule

    def delete(self, schedule_id: int) -> None:
        self.repo.delete(self.get(schedule_id))
        self.db.commit()

    @staticmethod
    def _apply(schedule: BackupSchedule, data: ScheduleIn) -> None:
        schedule.name = data.name
        schedule.cron = data.cron
        schedule.timezone = data.timezone
        schedule.scope = data.scope
        schedule.database_name = data.database if data.scope == "single" else None
        schedule.enabled = data.enabled
