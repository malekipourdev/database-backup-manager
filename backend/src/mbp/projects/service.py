"""Registering projects: validation, encrypted credentials and variables, deploy requests."""

import json
import logging

from sqlalchemy.orm import Session

from mbp.agent.deploy import (
    AUTH_TYPES,
    ENV_NAME_RE,
    valid_compose_file,
    valid_project,
    valid_ref,
    valid_repo_url,
)
from mbp.api.errors import ApiError
from mbp.db import utcnow
from mbp.logging import register_secret
from mbp.models import DbInstance, Deployment, Project
from mbp.repositories.project_repository import ProjectRepository
from mbp.security import crypto

logger = logging.getLogger(__name__)

# The panel's own compose project: deploying under this name would replace the panel.
RESERVED_NAMES = frozenset({"mysql-backup-panel"})
MAX_ENV_VARS = 200
MAX_ENV_VALUE = 32 * 1024


def env_of(project: Project) -> dict[str, str]:
    if not project.env_encrypted:
        return {}
    values = json.loads(crypto.decrypt(project.env_encrypted))
    for value in values.values():
        register_secret(value)
    return values


def credential_of(project: Project) -> str | None:
    if not project.credential_encrypted:
        return None
    value = crypto.decrypt(project.credential_encrypted)
    register_secret(value)
    return value


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ProjectRepository(db)

    def get(self, project_id: int) -> Project:
        project = self.repo.get(project_id)
        if project is None:
            raise ApiError(404, "project_not_found")
        return project

    def _check(self, data: dict, project: Project | None) -> None:
        fields: dict[str, str] = {}
        name = data.get("name", project.name if project else "")
        if not valid_project(name) or name in RESERVED_NAMES:
            fields["name"] = "invalid_project_name"
        elif (other := self.repo.get_by_name(name)) is not None and other is not project:
            fields["name"] = "name_taken"
        if "repo_url" in data and not valid_repo_url(data["repo_url"]):
            fields["repo_url"] = "invalid_repo_url"
        if "branch" in data and not valid_ref(data["branch"]):
            fields["branch"] = "invalid_ref"
        if "compose_file" in data and not valid_compose_file(data["compose_file"]):
            fields["compose_file"] = "invalid_compose_file"
        auth_type = data.get("auth_type", project.auth_type if project else "none")
        if auth_type not in AUTH_TYPES:
            fields["auth_type"] = "invalid"
        has_credential = bool(data.get("credential")) or (
            project is not None
            and project.credential_encrypted is not None
            and not data.get("clear_credential")
            and auth_type == project.auth_type
        )
        if auth_type != "none" and not has_credential:
            fields["credential"] = "required"
        instance_id = data.get("backup_instance_id")
        if instance_id is not None and self.db.get(DbInstance, instance_id) is None:
            fields["backup_instance_id"] = "instance_not_found"
        if fields:
            raise ApiError(422, "validation_error", fields=fields)

    def _apply_env(self, project: Project, changes: list[dict]) -> None:
        """`changes`: [{"name", "value" or None}]; None keeps the stored value, absent removes."""
        current = env_of(project)
        result: dict[str, str] = {}
        for item in changes:
            name = item["name"]
            if not ENV_NAME_RE.fullmatch(name):
                raise ApiError(422, "validation_error", fields={"env": "invalid_env_name"})
            if name in result:
                raise ApiError(422, "validation_error", fields={"env": "duplicate_env_name"})
            value = item.get("value")
            if value is None:
                if name not in current:
                    raise ApiError(422, "validation_error", fields={"env": "env_value_required"})
                value = current[name]
            if len(value) > MAX_ENV_VALUE:
                raise ApiError(422, "validation_error", fields={"env": "env_value_too_long"})
            result[name] = value
        if len(result) > MAX_ENV_VARS:
            raise ApiError(422, "validation_error", fields={"env": "too_many"})
        for value in result.values():
            register_secret(value)
        project.env_encrypted = crypto.encrypt(json.dumps(result)) if result else None

    def save(self, data: dict, project: Project | None = None) -> Project:
        self._check(data, project)
        if project is None:
            project = Project(backup_databases=[], backup_required=True, auth_type="none")
            self.repo.add(project)
        for field in (
            "name",
            "repo_url",
            "branch",
            "compose_file",
            "auth_type",
            "backup_instance_id",
            "backup_databases",
            "backup_required",
        ):
            if field in data:
                setattr(project, field, data[field])
        if data.get("credential"):
            register_secret(data["credential"])
            project.credential_encrypted = crypto.encrypt(data["credential"])
        elif data.get("clear_credential") or project.auth_type == "none":
            project.credential_encrypted = None
        if "env" in data:
            self._apply_env(project, data["env"])
        if not project.backup_instance_id:
            project.backup_databases = []
        self.db.commit()
        return project

    def request_deploy(
        self, project: Project, *, ref: str | None, trigger: str, actor: str
    ) -> Deployment:
        if ref is not None and not valid_ref(ref):
            raise ApiError(422, "validation_error", fields={"ref": "invalid_ref"})
        if self.repo.active_deployment(project.id) is not None:
            raise ApiError(409, "deploy_in_progress")
        deployment = Deployment(
            project_id=project.id,
            project_name=project.name,
            trigger=trigger,
            actor=actor[:100],
            ref=ref or project.branch,
            status="queued",
            log="",
            backup_run_ids=[],
            requested_at=utcnow(),
        )
        self.db.add(deployment)
        self.db.commit()
        logger.info(
            "%s (%s) asked to deploy %s at %s", actor, trigger, project.name, deployment.ref
        )
        return deployment
