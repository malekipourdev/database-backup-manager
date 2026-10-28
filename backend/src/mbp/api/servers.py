from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.schemas import ServerIn, ServerOut, ServerSetup, ServerUpdate
from mbp.api.scope import ServerScope, restriction
from mbp.apiaccess.servers import add_created_server
from mbp.db import get_db
from mbp.models import Server
from mbp.repositories.server_repository import ServerRepository
from mbp.servers.service import ServerService, install_command

router = APIRouter(tags=["servers"])


def _out(server: Server, repo: ServerRepository) -> ServerOut:
    return ServerOut(
        id=server.id,
        name=server.name,
        kind=server.kind,
        host=server.host,
        port=server.port,
        notes=server.notes,
        paired=server.paired,
        cert_fingerprint=server.cert_fingerprint,
        paired_at=server.paired_at,
        last_seen_at=server.last_seen_at,
        last_error=server.last_error,
        agent_hostname=server.agent_hostname,
        docker_version=server.docker_version,
        created_at=server.created_at,
        **repo.usage(server.id),
    )


@router.get("/servers", response_model=list[ServerOut])
def list_servers(
    db: Session = Depends(get_db), scope: ServerScope | None = Depends(restriction)
) -> list[ServerOut]:
    repo = ServerRepository(db)
    repo.local()
    return [_out(s, repo) for s in repo.list_all() if scope is None or scope.allows(s.id)]


@router.post("/servers", response_model=ServerSetup, status_code=201)
def create_server(body: ServerIn, request: Request, db: Session = Depends(get_db)) -> ServerSetup:
    service = ServerService(db)
    server, token = service.create(body.name, body.host, body.port, body.notes)
    add_created_server(request, db, server.id)
    return ServerSetup(
        server=_out(server, service.repo),
        token=token,
        install_command=install_command(server, token),
    )


@router.get("/servers/{server_id}", response_model=ServerOut)
def get_server(server_id: int, db: Session = Depends(get_db)) -> ServerOut:
    service = ServerService(db)
    return _out(service.get(server_id), service.repo)


@router.patch("/servers/{server_id}", response_model=ServerOut)
def update_server(server_id: int, body: ServerUpdate, db: Session = Depends(get_db)) -> ServerOut:
    service = ServerService(db)
    server = service.update(
        service.get(server_id), body.model_dump(exclude_unset=True, exclude_none=True)
    )
    return _out(server, service.repo)


@router.delete("/servers/{server_id}", status_code=204)
def delete_server(server_id: int, db: Session = Depends(get_db)) -> Response:
    service = ServerService(db)
    service.delete(service.get(server_id))
    return Response(status_code=204)


@router.post("/servers/{server_id}/connect", response_model=ServerOut)
def connect_server(server_id: int, db: Session = Depends(get_db)) -> ServerOut:
    """Check the agent; for another server, also verify it and pin its certificate."""
    service = ServerService(db)
    return _out(service.connect(service.get(server_id)), service.repo)


@router.post("/servers/{server_id}/token", response_model=ServerSetup)
def rotate_token(server_id: int, db: Session = Depends(get_db)) -> ServerSetup:
    """A new token (the old one stops working); the server must be connected again."""
    service = ServerService(db)
    server = service.get(server_id)
    token = service.rotate_token(server)
    return ServerSetup(
        server=_out(server, service.repo),
        token=token,
        install_command=install_command(server, token),
    )
