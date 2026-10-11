from fastapi import APIRouter, Depends, Response
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
from mbp.db import get_db
from mbp.services import mysql_probe
from mbp.services.instance_service import InstanceService
from mbp.services.mysql_probe import ConnParams, ProbeResult
from mbp.services.selection_service import SelectionService

router = APIRouter(tags=["instances"])


def _result(result: ProbeResult) -> ConnectionTestResult:
    return ConnectionTestResult.model_validate(result, from_attributes=True)


@router.get("/instances", response_model=list[Instance])
def list_instances(db: Session = Depends(get_db)) -> list[Instance]:
    return [Instance.model_validate(i) for i in InstanceService(db).list()]


@router.post("/instances", response_model=Instance, status_code=201)
def create_instance(body: InstanceCreate, db: Session = Depends(get_db)) -> Instance:
    return Instance.model_validate(InstanceService(db).create(body))


# Declared before the /instances/{instance_id} routes.
@router.post("/instances/test-connection", response_model=ConnectionTestResult)
def test_unsaved_connection(body: ConnectionParams) -> ConnectionTestResult:
    params = ConnParams(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password.get_secret_value(),
    )
    return _result(mysql_probe.test_connection(params))


@router.get("/instances/{instance_id}", response_model=Instance)
def get_instance(instance_id: int, db: Session = Depends(get_db)) -> Instance:
    return Instance.model_validate(InstanceService(db).get(instance_id))


@router.patch("/instances/{instance_id}", response_model=Instance)
def update_instance(
    instance_id: int, body: InstanceUpdate, db: Session = Depends(get_db)
) -> Instance:
    return Instance.model_validate(InstanceService(db).update(instance_id, body))


@router.delete("/instances/{instance_id}", status_code=204)
def delete_instance(instance_id: int, db: Session = Depends(get_db)) -> Response:
    InstanceService(db).delete(instance_id)
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
