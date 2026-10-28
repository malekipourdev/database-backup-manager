from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
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
from mbp.api.scope import ServerScope, key_servers, restriction
from mbp.apiaccess.keys import Actor, current_actor
from mbp.containers.service import ContainerService
from mbp.db import get_db
from mbp.models import Server
from mbp.repositories.container_repository import ContainerRepository
from mbp.repositories.server_repository import ServerRepository

router = APIRouter(tags=["containers"])
Ref = Path(pattern=ContainerRefPattern)


def get_server(
    request: Request,
    server: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> Server:
    """The `server` query parameter; the panel's own server when it is omitted."""
    repo = ServerRepository(db)
    row = repo.local() if server is None else repo.get(server)
    allowed = key_servers(request)
    if row is None or (allowed is not None and row.id not in allowed):
        raise ApiError(404, "server_not_found")
    return row


def service(
    request: Request, db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> ContainerService:
    return ContainerService(db, request.app.state.agents.for_server(server), server)


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
def get_container_settings(
    db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> ContainerSettingsIO:
    return _settings_out(ContainerRepository(db).get_settings(server.id))


@router.put("/containers/-/settings", response_model=ContainerSettingsIO)
def put_container_settings(
    body: ContainerSettingsIO, db: Session = Depends(get_db), server: Server = Depends(get_server)
) -> ContainerSettingsIO:
    row = ContainerRepository(db).get_settings_for_update(server.id)
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
    server: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    scope: ServerScope | None = Depends(restriction),
) -> ContainerActionPage:
    """The audit log of every server, or of one (`server`)."""
    items, total = ContainerRepository(db).actions_page(
        page, page_size, container, server, scope.server_ids if scope else None
    )
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
    who: Actor = Depends(current_actor),
    svc: ContainerService = Depends(service),
) -> dict:
    return {"container": svc.act(ref, action, actor=who.name, source=who.source)}
