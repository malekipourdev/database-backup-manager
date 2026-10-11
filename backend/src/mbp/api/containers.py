from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from mbp.api.schemas import (
    ContainerActionItem,
    ContainerActionPage,
    ContainerActionResult,
    ContainerDetails,
    ContainerList,
    ContainerLogs,
    ContainerRefPattern,
    ContainerSettingsIO,
    ContainerStatsMap,
    ContainerStatsOne,
    ServerInfo,
)
from mbp.containers.agent_client import AgentClient
from mbp.containers.service import ContainerService
from mbp.db import get_db
from mbp.models import AdminAccount
from mbp.repositories.container_repository import ContainerRepository
from mbp.security.sessions import require_session

router = APIRouter(tags=["containers"])
Ref = Path(pattern=ContainerRefPattern)


def get_agent(request: Request) -> AgentClient:
    return request.app.state.agent


def service(db: Session = Depends(get_db), agent: AgentClient = Depends(get_agent)):
    return ContainerService(db, agent)


@router.get("/containers", response_model=ContainerList)
def list_containers(svc: ContainerService = Depends(service)) -> ContainerList:
    return ContainerList(containers=svc.containers(), read_only=svc.settings.read_only)  # type: ignore[arg-type]


@router.get("/containers/-/info", response_model=ServerInfo)
def server_info(svc: ContainerService = Depends(service)) -> dict:
    return svc.info()


@router.get("/containers/-/stats", response_model=ContainerStatsMap)
def all_stats(svc: ContainerService = Depends(service)) -> dict:
    return {"stats": svc.stats()}


@router.get("/containers/-/settings", response_model=ContainerSettingsIO)
def get_container_settings(db: Session = Depends(get_db)) -> ContainerSettingsIO:
    return _settings_out(ContainerRepository(db).get_settings())


@router.put("/containers/-/settings", response_model=ContainerSettingsIO)
def put_container_settings(
    body: ContainerSettingsIO, db: Session = Depends(get_db)
) -> ContainerSettingsIO:
    row = ContainerRepository(db).get_settings_for_update()
    for field, value in body.model_dump().items():
        setattr(row, field, value)
    db.commit()
    return _settings_out(row)


def _settings_out(row) -> ContainerSettingsIO:
    return ContainerSettingsIO.model_validate(
        {field: getattr(row, field) for field in ContainerSettingsIO.model_fields}
    )


@router.get("/containers/-/actions", response_model=ContainerActionPage)
def list_actions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    container: str | None = Query(default=None, max_length=128),
    db: Session = Depends(get_db),
) -> ContainerActionPage:
    items, total = ContainerRepository(db).actions_page(page, page_size, container)
    return ContainerActionPage(
        items=[ContainerActionItem.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/containers/{ref}", response_model=ContainerDetails)
def get_container(ref: str = Ref, svc: ContainerService = Depends(service)) -> dict:
    return svc.container(ref)


@router.get("/containers/{ref}/stats", response_model=ContainerStatsOne)
def container_stats(ref: str = Ref, svc: ContainerService = Depends(service)) -> dict:
    return {"stats": svc.container_stats(ref)}


@router.get("/containers/{ref}/logs", response_model=ContainerLogs)
def container_logs(
    ref: str = Ref,
    tail: int = Query(default=200, ge=1, le=5000),
    svc: ContainerService = Depends(service),
) -> dict:
    return svc.logs(ref, tail)


@router.post("/containers/{ref}/{action}", response_model=ContainerActionResult)
def container_action(
    action: Literal["start", "stop", "restart"],
    ref: str = Ref,
    admin: AdminAccount = Depends(require_session),
    svc: ContainerService = Depends(service),
) -> dict:
    return {"container": svc.act(ref, action, actor=admin.username, source="panel")}
