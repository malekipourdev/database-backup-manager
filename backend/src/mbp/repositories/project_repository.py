from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from mbp.models import Deployment, Project

ACTIVE = ("queued", "running")


class ProjectRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(
        self, server_id: int | None = None, where: ColumnElement[bool] | None = None
    ) -> list[Project]:
        stmt = select(Project).order_by(Project.name)
        if server_id is not None:
            stmt = stmt.where(Project.server_id == server_id)
        if where is not None:
            stmt = stmt.where(where)
        return list(self.db.scalars(stmt))

    def get(self, project_id: int) -> Project | None:
        return self.db.get(Project, project_id)

    def get_by_name(self, name: str) -> Project | None:
        return self.db.scalar(select(Project).where(Project.name == name))

    def add(self, project: Project) -> None:
        self.db.add(project)

    def delete(self, project: Project) -> None:
        self.db.delete(project)

    # --- deployments ---

    def get_deployment(self, deployment_id: int) -> Deployment | None:
        return self.db.get(Deployment, deployment_id)

    def active_deployment(self, project_id: int) -> Deployment | None:
        stmt = select(Deployment).where(
            Deployment.project_id == project_id, Deployment.status.in_(ACTIVE)
        )
        return self.db.scalar(stmt.limit(1))

    def list_active(self) -> list[Deployment]:
        return list(self.db.scalars(select(Deployment).where(Deployment.status.in_(ACTIVE))))

    def last_deployments(self) -> dict[int, Deployment]:
        """The newest deployment of every project."""
        newest = (
            select(Deployment.project_id, func.max(Deployment.id).label("id"))
            .where(Deployment.project_id.is_not(None))
            .group_by(Deployment.project_id)
            .subquery()
        )
        rows = self.db.scalars(select(Deployment).join(newest, Deployment.id == newest.c.id))
        return {d.project_id: d for d in rows}

    def last_success(self, project_id: int) -> Deployment | None:
        stmt = (
            select(Deployment)
            .where(Deployment.project_id == project_id, Deployment.status == "success")
            .order_by(Deployment.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def deployments_page(
        self, project_id: int, page: int, page_size: int
    ) -> tuple[list[Deployment], int]:
        base = select(Deployment).where(Deployment.project_id == project_id)
        total = self.db.scalar(
            select(func.count()).select_from(Deployment).where(Deployment.project_id == project_id)
        )
        stmt = base.order_by(Deployment.id.desc()).offset((page - 1) * page_size).limit(page_size)
        return list(self.db.scalars(stmt)), total or 0
