"""Folders of projects: created on their own, renamed (projects follow), deleted when empty.

A project's files on its server are in <projects dir>/<folder>/<name>; after a rename they
move there on the project's next deploy (see mbp.agent.deploy).
"""

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from mbp.agent.deploy import folder_dir, valid_project
from mbp.api.errors import ApiError
from mbp.api.schemas import ProjectFolderIn, ProjectFolderOut
from mbp.db import get_db, utcnow
from mbp.models import Project, ProjectFolder
from mbp.projects.service import ensure_folder

router = APIRouter(tags=["projects"])


def _check_name(db: Session, name: str, folder: ProjectFolder | None) -> None:
    others = [f for f in db.scalars(select(ProjectFolder)) if f is not folder]
    directory = folder_dir(name)
    if directory is None:
        raise ApiError(422, "validation_error", fields={"name": "invalid_folder"})
    if any(f.name == name or folder_dir(f.name) == directory for f in others):
        raise ApiError(409, "folder_exists")
    if valid_project(directory.lower()) and db.scalar(
        select(Project).where(Project.name == directory)
    ):
        # Its directory would be the project's own checkout.
        raise ApiError(409, "folder_is_a_project")


def _out(db: Session) -> list[ProjectFolderOut]:
    counts = dict(
        db.execute(
            select(Project.folder, func.count(Project.id))
            .where(Project.folder.is_not(None))
            .group_by(Project.folder)
        ).all()
    )
    for name in counts:
        ensure_folder(db, name)
    db.commit()
    folders = db.scalars(select(ProjectFolder).order_by(ProjectFolder.name))
    return [
        ProjectFolderOut(
            id=f.id, name=f.name, created_at=f.created_at, projects=counts.get(f.name, 0)
        )
        for f in folders
    ]


def _folder(db: Session, folder_id: int) -> ProjectFolder:
    folder = db.get(ProjectFolder, folder_id)
    if folder is None:
        raise ApiError(404, "folder_not_found")
    return folder


@router.get("/project-folders", response_model=list[ProjectFolderOut])
def list_folders(db: Session = Depends(get_db)) -> list[ProjectFolderOut]:
    return _out(db)


@router.post("/project-folders", response_model=ProjectFolderOut, status_code=201)
def create_folder(body: ProjectFolderIn, db: Session = Depends(get_db)) -> ProjectFolderOut:
    _check_name(db, body.name, None)
    folder = ProjectFolder(name=body.name, created_at=utcnow())
    db.add(folder)
    db.commit()
    return ProjectFolderOut(id=folder.id, name=folder.name, created_at=folder.created_at)


@router.patch("/project-folders/{folder_id}", response_model=ProjectFolderOut)
def rename_folder(
    body: ProjectFolderIn, folder_id: int = Path(ge=1), db: Session = Depends(get_db)
) -> ProjectFolderOut:
    folder = _folder(db, folder_id)
    if body.name != folder.name:
        _check_name(db, body.name, folder)
        db.execute(update(Project).where(Project.folder == folder.name).values(folder=body.name))
        folder.name = body.name
        db.commit()
    return next(f for f in _out(db) if f.id == folder_id)


@router.delete("/project-folders/{folder_id}", status_code=204)
def delete_folder(folder_id: int = Path(ge=1), db: Session = Depends(get_db)) -> Response:
    folder = _folder(db, folder_id)
    if db.scalar(select(func.count(Project.id)).where(Project.folder == folder.name)):
        raise ApiError(409, "folder_not_empty")
    db.delete(folder)
    db.commit()
    return Response(status_code=204)
