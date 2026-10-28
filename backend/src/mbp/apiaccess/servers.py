"""API keys limited to some servers.

Such a key (ApiKey.server_ids) reaches only what is on, or belongs to, those servers:
the servers themselves, their databases with the backups and schedules of those, their
containers, projects with their deployments, and web servers with their health checks. A
thing on another server answers as if it did not exist (404). Lists leave the others out
(the routes do it, with mbp.api.scope), and a server named in a request body must be one of
the key's (422).

What is not any one server's is the whole panel's, and several pieces of software sharing
the panel must not change it for each other: those settings can be read (backup settings,
remote storage, retention) or not even read (alert channels, bots, webhooks), and never
changed. Project folders are listed as far as the key's projects use them.

A server added with such a key joins the key's servers.
"""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.scope import ServerScope, key_servers, restriction
from mbp.apiaccess import scopes
from mbp.apiaccess.keys import require_api_key
from mbp.db import get_db
from mbp.models import ApiKey, BackupRun, BackupSchedule, DbInstance, Deployment, Project, WebCheck

# Areas a limited key cannot use at all: they hold the whole panel's alert routing.
HIDDEN_AREAS = frozenset({"notifications", "bots", "webhooks"})
# Areas whose settings are the whole panel's, except what is under one database.
PANEL_WIDE_AREAS = frozenset({"backup-settings", "storage"})
FOLDERS = "/project-folders"
REFUSED = "server_restricted"


def _refuse(request: Request, status: int, code: str) -> ApiError:
    request.state.api_error = code
    return ApiError(status, code)


def _instance_server(db: Session, instance_id: int | None) -> tuple[bool, int | None]:
    """(exists, its server_id) of a database."""
    instance = db.get(DbInstance, instance_id) if instance_id is not None else None
    return (instance is not None, instance.server_id if instance else None)


def _reachable(db: Session, scope: ServerScope, name: str, value: str) -> bool:
    """Whether the thing a path parameter names is on the key's servers. A thing that does
    not exist is "reachable": the route answers its own 404 (or validation error)."""
    try:
        ident = int(value)
    except ValueError:
        return True
    if name == "server_id":
        return scope.allows(ident)
    if name == "instance_id":
        exists, server_id = _instance_server(db, ident)
        return not exists or scope.allows(server_id)
    if name == "run_id":
        run = db.get(BackupRun, ident)
        if run is None:
            return True
        # The backups of a deleted database belong to no server any more.
        exists, server_id = _instance_server(db, run.instance_id)
        return exists and scope.allows(server_id)
    if name == "schedule_id":
        schedule = db.get(BackupSchedule, ident)
        if schedule is None:
            return True
        exists, server_id = _instance_server(db, schedule.instance_id)
        return exists and scope.allows(server_id)
    if name == "project_id":
        project = db.get(Project, ident)
        return project is None or scope.allows(project.server_id)
    if name == "deployment_id":
        deployment = db.get(Deployment, ident)
        if deployment is None:
            return True
        project = db.get(Project, deployment.project_id) if deployment.project_id else None
        return project is not None and scope.allows(project.server_id)
    if name == "check_id":
        check = db.get(WebCheck, ident)
        return check is None or scope.allows(check.server_id)
    return True


# Path parameter -> the error a thing on another server answers with (as if missing).
CHECKED_PARAMS: dict[str, str] = {
    "server_id": "server_not_found",
    "instance_id": "instance_not_found",
    "run_id": "run_not_found",
    "schedule_id": "schedule_not_found",
    "project_id": "project_not_found",
    "deployment_id": "deployment_not_found",
    "check_id": "check_not_found",
}


def enforce_servers(
    request: Request,
    _: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
    scope: ServerScope | None = Depends(restriction),
) -> None:
    """Refuses what a key limited to some servers may not reach (a no-op for other keys)."""
    if scope is None:
        return
    route = request.scope.get("route")
    tags = getattr(route, "tags", None) or []
    area = tags[0] if tags else ""
    path = getattr(route, "path", "")
    write = scopes.required_scope(request.method, area, path).endswith(":write")
    if area in HIDDEN_AREAS:
        raise _refuse(request, 403, REFUSED)
    panel_wide = area in PANEL_WIDE_AREAS and "{instance_id}" not in path
    if write and (panel_wide or path.startswith(FOLDERS)):
        raise _refuse(request, 403, REFUSED)
    raw = request.query_params.get("server")
    if raw is not None and raw.isdigit() and not scope.allows(int(raw)):
        raise _refuse(request, 404, "server_not_found")
    for name, value in request.path_params.items():
        if name in CHECKED_PARAMS and not _reachable(db, scope, name, str(value)):
            raise _refuse(request, 404, CHECKED_PARAMS[name])


def add_created_server(request: Request, db: Session, server_id: int) -> None:
    """A server added with a limited key joins the key's servers."""
    key: ApiKey | None = getattr(request.state, "api_key", None)
    if key is None or key.server_ids is None or key_servers(request) is None:
        return
    key.server_ids = sorted({*key.server_ids, server_id})
    db.commit()
