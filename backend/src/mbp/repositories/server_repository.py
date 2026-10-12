from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbp.models import DbInstance, Project, Server

LOCAL_NAME = "main"


class ServerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, server_id: int) -> Server | None:
        return self.db.get(Server, server_id)

    def list_all(self) -> list[Server]:
        # The local server first, then by name.
        stmt = select(Server).order_by((Server.kind == "local").desc(), Server.name_normalized)
        return list(self.db.scalars(stmt))

    def get_by_name(self, name: str) -> Server | None:
        stmt = select(Server).where(Server.name_normalized == name.strip().lower())
        return self.db.scalar(stmt)

    def local(self) -> Server:
        """The panel's own server (created if missing, e.g. in a database made by hand)."""
        row = self.db.scalar(select(Server).where(Server.kind == "local"))
        if row is None:
            row = Server(name=LOCAL_NAME, name_normalized=LOCAL_NAME, kind="local", notes="")
            self.db.add(row)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                row = self.db.scalar(select(Server).where(Server.kind == "local"))
                if row is None:
                    raise
        return row

    def usage(self, server_id: int) -> dict[str, int]:
        """What still uses a server: it cannot be deleted while anything does."""
        projects = self.db.scalar(
            select(func.count()).select_from(Project).where(Project.server_id == server_id)
        )
        instances = self.db.scalar(
            select(func.count()).select_from(DbInstance).where(DbInstance.server_id == server_id)
        )
        return {"projects": projects or 0, "instances": instances or 0}
