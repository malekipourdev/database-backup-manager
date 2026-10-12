from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import ScheduleIn, ScheduleOut, SchedulePreview, SchedulePreviewRequest
from mbp.api.scope import ServerScope, server_scope
from mbp.backups.scheduler import BackupScheduler, next_fire_times
from mbp.db import get_db
from mbp.models import BackupSchedule, DbInstance
from mbp.services.schedule_service import ScheduleService, next_run_at

router = APIRouter(tags=["schedules"])


def get_scheduler(request: Request) -> BackupScheduler | None:
    return getattr(request.app.state, "backup_scheduler", None)


def schedule_out(db: Session, schedule: BackupSchedule) -> ScheduleOut:
    instance = db.get(DbInstance, schedule.instance_id)
    return ScheduleOut(
        id=schedule.id,
        instance_id=schedule.instance_id,
        instance_name=instance.name if instance else "",
        name=schedule.name,
        cron=schedule.cron,
        timezone=schedule.timezone,
        scope=schedule.scope,  # type: ignore[arg-type]
        database=schedule.database_name,
        enabled=schedule.enabled,
        next_run_at=next_run_at(schedule),
        last_fired_at=schedule.last_fired_at,
        last_result=schedule.last_result,
        last_detail=schedule.last_detail,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


def _sync(scheduler: BackupScheduler | None, schedule_id: int) -> None:
    if scheduler is not None and scheduler.running:
        scheduler.sync(schedule_id)


@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(
    db: Session = Depends(get_db), scope: ServerScope | None = Depends(server_scope)
) -> list[ScheduleOut]:
    instances = scope.instances() if scope else None
    return [schedule_out(db, s) for s in ScheduleService(db).list_all(None, instances)]


@router.post("/schedules/preview", response_model=SchedulePreview)
def preview_schedule(body: SchedulePreviewRequest) -> SchedulePreview:
    try:
        return SchedulePreview(next_runs=next_fire_times(body.cron, body.timezone, count=5))
    except ValueError as exc:
        field = "timezone" if str(exc) == "invalid_timezone" else "cron"
        raise ApiError(422, "validation_error", fields={field: str(exc)}) from exc


@router.get("/instances/{instance_id}/schedules", response_model=list[ScheduleOut])
def list_instance_schedules(instance_id: int, db: Session = Depends(get_db)) -> list[ScheduleOut]:
    return [schedule_out(db, s) for s in ScheduleService(db).list_all(instance_id)]


@router.post("/instances/{instance_id}/schedules", response_model=ScheduleOut, status_code=201)
def create_schedule(
    instance_id: int,
    body: ScheduleIn,
    db: Session = Depends(get_db),
    scheduler: BackupScheduler | None = Depends(get_scheduler),
) -> ScheduleOut:
    schedule = ScheduleService(db).create(instance_id, body)
    _sync(scheduler, schedule.id)
    return schedule_out(db, schedule)


@router.get("/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int, db: Session = Depends(get_db)) -> ScheduleOut:
    return schedule_out(db, ScheduleService(db).get(schedule_id))


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    body: ScheduleIn,
    db: Session = Depends(get_db),
    scheduler: BackupScheduler | None = Depends(get_scheduler),
) -> ScheduleOut:
    schedule = ScheduleService(db).update(schedule_id, body)
    _sync(scheduler, schedule.id)
    return schedule_out(db, schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    scheduler: BackupScheduler | None = Depends(get_scheduler),
) -> Response:
    ScheduleService(db).delete(schedule_id)
    _sync(scheduler, schedule_id)
    return Response(status_code=204)


@router.post("/schedules/{schedule_id}/run", response_model=ScheduleOut)
def run_schedule_now(
    schedule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    scheduler: BackupScheduler | None = Depends(get_scheduler),
) -> ScheduleOut:
    """Run a schedule now, even if it is disabled; the result is shown as its last run."""
    ScheduleService(db).get(schedule_id)
    db.commit()
    if scheduler is None:
        raise ApiError(503, "scheduler_unavailable")
    scheduler.fire(schedule_id, force=True)
    db.expire_all()
    return schedule_out(db, ScheduleService(db).get(schedule_id))
