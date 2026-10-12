from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.schemas import (
    ConnectionParams,
    ConnectionTestResult,
    DatabaseList,
    Instance,
    InstanceCreate,
    InstanceUpdate,
    SelectionUpdate,
)
from mbp.api.scope import ServerScope, server_scope
from mbp.db import get_db
from mbp.servers import db_access
from mbp.services.instance_service import InstanceService, check_server
from mbp.services.mysql_probe import ConnParams, ProbeResult
from mbp.services.selection_service import SelectionService

router = APIRouter(tags=["instances"])


def _result(result: ProbeResult) -> ConnectionTestResult:
    return ConnectionTestResult.model_validate(result, from_attributes=True)


@router.get("/instances", response_model=list[Instance])
def list_instances(
    db: Session = Depends(get_db), scope: ServerScope | None = Depends(server_scope)
) -> list[Instance]:
    where = scope.instances() if scope else None
    return [Instance.model_validate(i) for i in InstanceService(db).list(where)]


@router.post("/instances", response_model=Instance, status_code=201)
def create_instance(body: InstanceCreate, db: Session = Depends(get_db)) -> Instance:
    return Instance.model_validate(InstanceService(db).create(body))


# Declared before the /instances/{instance_id} routes.
@router.post("/instances/test-connection", response_model=ConnectionTestResult)
def test_unsaved_connection(
    body: ConnectionParams, db: Session = Depends(get_db)
) -> ConnectionTestResult:
    check_server(db, body.server_id)
    db.commit()
    params = ConnParams(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password.get_secret_value(),
    )
    return _result(db_access.test_connection(body.server_id, params))


@router.get("/instances/{instance_id}", response_model=Instance)
def get_instance(instance_id: int, db: Session = Depends(get_db)) -> Instance:
    return Instance.model_validate(InstanceService(db).get(instance_id))


@router.patch("/instances/{instance_id}", response_model=Instance)
def update_instance(
    instance_id: int, body: InstanceUpdate, db: Session = Depends(get_db)
) -> Instance:
    return Instance.model_validate(InstanceService(db).update(instance_id, body))


@router.delete("/instances/{instance_id}", status_code=204)
def delete_instance(instance_id: int, request: Request, db: Session = Depends(get_db)) -> Response:
    InstanceService(db).delete(instance_id)
    # The instance's schedules were deleted with it (ON DELETE CASCADE).
    scheduler = getattr(request.app.state, "backup_scheduler", None)
    if scheduler is not None and scheduler.running:
        scheduler.sync_all()
    return Response(status_code=204)


@router.post("/instances/{instance_id}/test-connection", response_model=ConnectionTestResult)
def test_saved_connection(instance_id: int, db: Session = Depends(get_db)) -> ConnectionTestResult:
    return _result(InstanceService(db).test_saved(instance_id))


@router.get("/instances/{instance_id}/databases", response_model=DatabaseList)
def list_databases(instance_id: int, db: Session = Depends(get_db)) -> DatabaseList:
    return SelectionService(db).get_listing(instance_id)


@router.put("/instances/{instance_id}/selection", response_model=DatabaseList)
def save_selection(
    instance_id: int, body: SelectionUpdate, db: Session = Depends(get_db)
) -> DatabaseList:
    return SelectionService(db).save(instance_id, body.databases)
