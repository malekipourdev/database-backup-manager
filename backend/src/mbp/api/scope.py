"""The `server` query parameter of list endpoints: only what belongs to one server.

A database belongs to the panel's own server when the panel connects to it itself
(server_id NULL), and to another server when that server's agent reaches it.
"""

from dataclasses import dataclass

from fastapi import Depends, Query
from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.db import get_db
from mbp.models import DbInstance
from mbp.repositories.server_repository import ServerRepository


@dataclass(frozen=True)
class ServerScope:
    server_id: int
    local: bool

    def instances(self) -> ColumnElement[bool]:
        """The condition on DbInstance for this server's databases."""
        if self.local:
            return DbInstance.server_id.is_(None)
        return DbInstance.server_id == self.server_id


def server_scope(
    server: int | None = Query(default=None, ge=1), db: Session = Depends(get_db)
) -> ServerScope | None:
    """None: every server (the parameter was not given)."""
    if server is None:
        return None
    row = ServerRepository(db).get(server)
    if row is None:
        raise ApiError(404, "server_not_found")
    return ServerScope(server_id=row.id, local=row.is_local)
