"""Which servers a request covers: the `server` query parameter of list endpoints, and the
servers an API key is limited to (mbp.apiaccess.servers).

A database belongs to the panel's own server when the panel connects to it itself
(server_id NULL), and to another server when that server's agent reaches it.
"""

from dataclasses import dataclass

from fastapi import Depends, Query, Request
from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.db import get_db
from mbp.models import DbInstance, Project, Server
from mbp.repositories.server_repository import ServerRepository


@dataclass(frozen=True)
class ServerScope:
    server_ids: frozenset[int]
    # The panel's own server, when known: its databases have no server_id.
    local_id: int | None = None
    # Narrowed by a key limited to some servers, not only by the `server` parameter.
    restricted: bool = False

    @classmethod
    def of(cls, server: Server) -> "ServerScope":
        """One server."""
        return cls(frozenset({server.id}), server.id if server.is_local else None)

    @property
    def local(self) -> bool:
        return self.local_id is not None and self.local_id in self.server_ids

    def allows(self, server_id: int | None) -> bool:
        """`server_id` None is the panel's own server (as on a database)."""
        if server_id is None:
            return self.local
        return server_id in self.server_ids

    def allows_instance(self, instance: DbInstance) -> bool:
        return self.allows(instance.server_id)

    def instances(self) -> ColumnElement[bool]:
        """The condition on DbInstance for these servers' databases."""
        conditions: list[ColumnElement[bool]] = []
        others = sorted(self.server_ids - {self.local_id})
        if others:
            conditions.append(DbInstance.server_id.in_(others))
        if self.local:
            conditions.append(DbInstance.server_id.is_(None))
        return or_(*conditions) if conditions else false()

    def projects(self) -> ColumnElement[bool]:
        return Project.server_id.in_(sorted(self.server_ids))


def key_servers(request: Request) -> frozenset[int] | None:
    """The servers the request's API key is limited to; None: every server (or no key)."""
    return getattr(request.state, "api_servers", None)


def restriction(request: Request, db: Session = Depends(get_db)) -> ServerScope | None:
    """The servers the API key reaches, or None when it reaches every server."""
    allowed = key_servers(request)
    if allowed is None:
        return None
    return ServerScope(allowed, ServerRepository(db).local().id, restricted=True)


def server_scope(
    request: Request,
    server: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> ServerScope | None:
    """None: every server (the parameter was not given, and the key is not limited)."""
    allowed = key_servers(request)
    repo = ServerRepository(db)
    if server is None:
        if allowed is None:
            return None
        return ServerScope(allowed, repo.local().id, restricted=True)
    row = repo.get(server)
    if row is None or (allowed is not None and row.id not in allowed):
        raise ApiError(404, "server_not_found")
    return ServerScope(frozenset({row.id}), repo.local().id, restricted=allowed is not None)


def check_server_field(scope: ServerScope | None, field: str, server_id: int | None) -> None:
    """A server named in a request body must be one the key reaches (None: the panel's own)."""
    if scope is not None and not scope.allows(server_id):
        raise ApiError(422, "validation_error", fields={field: "server_not_found"})


def known_server_ids(db: Session, values: list[int] | None) -> list[int] | None:
    """The servers of an API key or webhook: known ones only; None: every server."""
    if values is None:
        return None
    wanted = sorted(set(values))
    known = set(db.scalars(select(Server.id).where(Server.id.in_(wanted))))
    if len(known) != len(wanted):
        raise ApiError(422, "validation_error", fields={"server_ids": "server_not_found"})
    return wanted
