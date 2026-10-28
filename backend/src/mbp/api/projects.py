from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import (
    DeployIn,
    DeploymentDetail,
    DeploymentPage,
    DeploymentSummary,
    ProjectIn,
    ProjectOut,
    ProjectState,
)
from mbp.api.scope import ServerScope, check_server_field, restriction, server_scope
from mbp.apiaccess.keys import Actor, current_actor
from mbp.db import get_db
from mbp.models import DbInstance, Project, Server
from mbp.projects.service import ProjectService, env_of
from mbp.repositories.project_repository import ProjectRepository

router = APIRouter(tags=["projects"])


def _out(project: Project, repo: ProjectRepository, last=None) -> ProjectOut:
    last = last if last is not None else repo.last_deployments().get(project.id)
    success = repo.last_success(project.id)
    server = repo.db.get(Server, project.server_id)
    return ProjectOut(
        id=project.id,
        name=project.name,
        folder=project.folder,
        server_id=project.server_id,
        server_name=server.name if server else "",
        repo_url=project.repo_url,
        branch=project.branch,
        compose_file=project.compose_file,
        auth_type=project.auth_type,
        has_credential=project.credential_encrypted is not None,
        env_names=list(env_of(project)),
        backup_instance_id=project.backup_instance_id,
        backup_databases=list(project.backup_databases or []),
        backup_required=project.backup_required,
        web_domains=list(project.web_domains or []),
        web_target=project.web_target,
        build_server_id=project.build_server_id,
        build_server_name=(
            build.name
            if project.build_server_id and (build := repo.db.get(Server, project.build_server_id))
            else None
        ),
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_deployment=DeploymentSummary.model_validate(last) if last else None,
        last_success=DeploymentSummary.model_validate(success) if success else None,
    )


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), scope: ServerScope | None = Depends(server_scope)
) -> list[ProjectOut]:
    repo = ProjectRepository(db)
    last = repo.last_deployments()
    projects = repo.list_all(where=scope.projects() if scope else None)
    return [_out(p, repo, last.get(p.id) or False) for p in projects]


def _check_servers(db: Session, scope: ServerScope | None, body: ProjectIn) -> None:
    """With a key limited to some servers: the project's servers and database are its own."""
    if scope is None:
        return
    check_server_field(scope, "server_id", body.server_id)
    if body.build_server_id is not None:
        check_server_field(scope, "build_server_id", body.build_server_id)
    if body.backup_instance_id is not None:
        instance = db.get(DbInstance, body.backup_instance_id)
        if instance is not None and not scope.allows_instance(instance):
            fields = {"backup_instance_id": "instance_not_found"}
            raise ApiError(422, "validation_error", fields=fields)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectIn,
    db: Session = Depends(get_db),
    scope: ServerScope | None = Depends(restriction),
) -> ProjectOut:
    _check_servers(db, scope, body)
    project = ProjectService(db).save(body.to_data())
    return _out(project, ProjectRepository(db))


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectOut:
    return _out(ProjectService(db).get(project_id), ProjectRepository(db))


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: ProjectIn,
    db: Session = Depends(get_db),
    scope: ServerScope | None = Depends(restriction),
) -> ProjectOut:
    service = ProjectService(db)
    project = service.get(project_id)
    server_id = body.server_id or project.server_id
    _check_servers(db, scope, body.model_copy(update={"server_id": server_id}))
    deployed = service.repo.last_deployments().get(project.id)
    if project.name != body.name and deployed:
        # The name is the compose project and directory on the server: renaming would
        # leave the deployed containers behind.
        raise ApiError(422, "validation_error", fields={"name": "rename_after_deploy"})
    if body.server_id is not None and body.server_id != project.server_id and deployed:
        # Same for moving it: delete it (with its containers) and add it on the other server.
        raise ApiError(422, "validation_error", fields={"server_id": "move_after_deploy"})
    return _out(service.save(body.to_data(), project), service.repo)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    request: Request,
    down: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> Response:
    service = ProjectService(db)
    project = service.get(project_id)
    if service.repo.active_deployment(project.id) is not None:
        raise ApiError(409, "deploy_in_progress")
    if service.repo.last_deployments().get(project.id):
        # Stop and remove its containers (down) and the checkout on the server.
        try:
            agent = request.app.state.agents.get(project.server_id)
            agent.project_remove(project.name, project.compose_file, down, project.folder)
        except ApiError:
            if down:
                raise
    service.repo.delete(project)
    db.commit()
    return Response(status_code=204)


@router.post("/projects/{project_id}/deploy", response_model=DeploymentSummary, status_code=202)
def deploy_project(
    project_id: int,
    body: DeployIn,
    request: Request,
    who: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
) -> DeploymentSummary:
    service = ProjectService(db)
    deployment = service.request_deploy(
        service.get(project_id), ref=body.ref or None, trigger=who.source, actor=who.name
    )
    request.app.state.deploy_runner.submit(deployment.id)
    return DeploymentSummary.model_validate(deployment)


@router.get("/projects/{project_id}/deployments", response_model=DeploymentPage)
def list_deployments(
    project_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> DeploymentPage:
    ProjectService(db).get(project_id)
    items, total = ProjectRepository(db).deployments_page(project_id, page, page_size)
    return DeploymentPage(
        items=[DeploymentSummary.model_validate(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/projects/{project_id}/state", response_model=ProjectState)
def project_state(project_id: int, request: Request, db: Session = Depends(get_db)) -> ProjectState:
    project = ProjectService(db).get(project_id)
    try:
        state = request.app.state.agents.get(project.server_id).project_state(
            project.name, project.folder
        )
    except ApiError as exc:
        return ProjectState(available=False, error_code=exc.code)
    return ProjectState(available=True, **state)


@router.get("/deployments/{deployment_id}", response_model=DeploymentDetail)
def get_deployment(
    deployment_id: int,
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DeploymentDetail:
    deployment = ProjectRepository(db).get_deployment(deployment_id)
    if deployment is None:
        raise ApiError(404, "deployment_not_found")
    summary = DeploymentSummary.model_validate(deployment).model_dump()
    return DeploymentDetail(**summary, log=deployment.log[offset:], log_size=len(deployment.log))
