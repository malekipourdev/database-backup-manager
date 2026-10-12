"""Runs deploys in the background: the pre-deploy backup, then the agent's job, with its log."""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session, sessionmaker

from mbp.api.errors import ApiError
from mbp.db import utcnow
from mbp.models import BackupRun, Deployment, Project, Server
from mbp.notifications.events import Event
from mbp.projects.service import credential_of, env_of
from mbp.repositories.project_repository import ProjectRepository
from mbp.services.backup_service import BackupService

logger = logging.getLogger(__name__)

MAX_LOG_CHARS = 1_000_000
# How long the agent may be unreachable during a deploy before it is given up.
AGENT_GRACE_SECONDS = 120
BACKUP_TIMEOUT_SECONDS = 6 * 3600
INTERRUPTED = "Interrupted by panel restart or shutdown."


class _Failed(Exception):
    def __init__(self, code: str, detail: str | None = None, *, logged: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
        # The agent already wrote the failure into the log.
        self.logged = logged


class DeployRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        backups,
        store,
        agents: Callable[[], object],
        *,
        notifier=None,
        poll_seconds: float = 1.0,
        workers: int = 2,
    ) -> None:
        self.session_factory = session_factory
        self.backups = backups
        self.store = store
        # () -> mbp.servers.registry.AgentRegistry
        self.agents = agents
        self.notifier = notifier
        self.poll_seconds = poll_seconds
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mbp-deploy")
        self._stopping = threading.Event()

    def recover(self) -> int:
        """Fail deploys left queued/running by a previous process."""
        with self.session_factory() as db:
            stale = ProjectRepository(db).list_active()
            for deployment in stale:
                deployment.status = "failed"
                deployment.error_code = "interrupted"
                deployment.error_detail = INTERRUPTED
                deployment.finished_at = utcnow()
            db.commit()
        return len(stale)

    def stop(self) -> None:
        self._stopping.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, deployment_id: int, on_done: Callable[[int], None] | None = None):
        """Queue a deploy; `on_done(deployment_id)` is called when it has finished."""

        def task() -> None:
            self.run(deployment_id)
            if on_done is not None:
                try:
                    on_done(deployment_id)
                except Exception:
                    logger.exception("Deploy %s: completion callback failed", deployment_id)

        return self._executor.submit(task)

    # --- one deploy ---

    def _update(self, deployment_id: int, *, lines: list[str] | None = None, **values) -> None:
        with self.session_factory() as db:
            deployment = db.get(Deployment, deployment_id)
            if deployment is None:
                return
            for key, value in values.items():
                setattr(deployment, key, value)
            if lines:
                log = deployment.log + "".join(f"{line}\n" for line in lines)
                if len(log) > MAX_LOG_CHARS:
                    log = "[…earlier lines removed…]\n" + log[-MAX_LOG_CHARS:]
                deployment.log = log
            db.commit()

    def run(self, deployment_id: int) -> None:
        try:
            self._run(deployment_id)
        except _Failed as exc:
            self._finish(deployment_id, "failed", exc.code, exc.detail, logged=exc.logged)
        except Exception:
            logger.exception("Deploy %s failed unexpectedly", deployment_id)
            self._finish(deployment_id, "failed", "internal_error", None)

    def _run(self, deployment_id: int) -> None:
        with self.session_factory() as db:
            deployment = db.get(Deployment, deployment_id)
            if deployment is None or deployment.status != "queued":
                return
            project = ProjectRepository(db).get(deployment.project_id or 0)
            if project is None:
                raise _Failed("project_not_found")
            server_id = project.server_id
            payload = {
                "project": project.name,
                "repo_url": project.repo_url,
                "ref": deployment.ref,
                "compose_file": project.compose_file,
                "env": env_of(project),
                "auth_type": project.auth_type,
                "credential": credential_of(project),
            }
            backup = (
                project.backup_instance_id,
                list(project.backup_databases or []),
                project.backup_required,
            )
        self._update(deployment_id, status="running", started_at=utcnow())
        if backup[0] and backup[1]:
            self._backup(deployment_id, *backup)
        self._deploy(deployment_id, server_id, payload)

    def _backup(self, deployment_id: int, instance_id: int, names: list[str], required: bool):
        self._update(
            deployment_id,
            step="backup",
            lines=[f"Backing up before the deploy: {', '.join(names)}"],
        )
        run_ids: list[int] = []
        problems: list[str] = []
        with self.session_factory() as db:
            service = BackupService(db, self.backups, self.store)
            for name in names:
                try:
                    created, skipped = service.start(instance_id, "single", name, trigger="deploy")
                except ApiError as exc:
                    problems.append(f"{name}: {exc.code}")
                    continue
                run_ids += [run.id for run in created]
                if skipped:
                    problems.append(f"{name}: already_in_progress")
        self._update(deployment_id, backup_run_ids=run_ids)
        deadline = time.monotonic() + BACKUP_TIMEOUT_SECONDS
        while run_ids and not self._stopping.is_set():
            with self.session_factory() as db:
                runs = [db.get(BackupRun, run_id) for run_id in run_ids]
                done = all(run is None or run.status in ("success", "failed") for run in runs)
                if done:
                    for run in runs:
                        if run is not None and run.status == "failed":
                            problems.append(f"{run.database_name}: {run.error_code}")
                    break
            if time.monotonic() > deadline:
                problems.append("timeout")
                break
            time.sleep(self.poll_seconds)
        if problems:
            line = f"Backup problems: {'; '.join(problems)}"
            self._update(deployment_id, lines=[line])
            if required:
                raise _Failed("backup_failed", "; ".join(problems)[:300])
        else:
            self._update(deployment_id, lines=["Backup done."])

    def _deploy(self, deployment_id: int, server_id: int, payload: dict) -> None:
        try:
            agent = self.agents().get(server_id)
        except ApiError as exc:
            raise _Failed(exc.code) from exc
        self._update(deployment_id, step="fetch")
        try:
            job_id = agent.deploy(payload)
        except ApiError as exc:
            raise _Failed(exc.code, exc.detail) from exc
        offset = 0
        unreachable_since: float | None = None
        while not self._stopping.is_set():
            try:
                view = agent.deploy_job(job_id, offset)
                unreachable_since = None
            except ApiError as exc:
                if exc.code == "job_not_found":
                    raise _Failed("agent_restarted") from exc
                unreachable_since = unreachable_since or time.monotonic()
                if time.monotonic() - unreachable_since > AGENT_GRACE_SECONDS:
                    raise _Failed(exc.code) from exc
                time.sleep(self.poll_seconds)
                continue
            offset = view["next_offset"]
            self._update(
                deployment_id,
                lines=view["lines"],
                step=view["step"],
                commit_sha=view.get("commit_sha"),
                commit_message=view.get("commit_message"),
            )
            if view["status"] != "running":
                if view["status"] == "success":
                    self._finish(deployment_id, "success")
                else:
                    raise _Failed(
                        view.get("error_code") or "deploy_failed",
                        view.get("error_detail"),
                        logged=bool(view.get("error_code")),
                    )
                return
            time.sleep(self.poll_seconds)

    def _finish(
        self,
        deployment_id: int,
        status: str,
        code: str | None = None,
        detail: str | None = None,
        *,
        logged: bool = False,
    ) -> None:
        values = {"status": status, "finished_at": utcnow()}
        if status == "failed":
            values |= {"error_code": code, "error_detail": (detail or None) and detail[:300]}
        if status == "success":
            lines = ["✔ Deployed."]
        else:
            lines = [] if logged else [f"✖ {code}" + (f": {detail}" if detail else "")]
        self._update(deployment_id, lines=lines, **values)
        self._notify(deployment_id)

    def _notify(self, deployment_id: int) -> None:
        if self.notifier is None:
            return
        with self.session_factory() as db:
            d = db.get(Deployment, deployment_id)
            if d is None:
                return
            params = {
                "project": d.project_name,
                "project_id": d.project_id,
                "deployment_id": d.id,
                "commit": (d.commit_sha or "")[:8],
                "message": d.commit_message or "",
                "actor": d.actor,
                "trigger": d.trigger,
                "error": d.error_code,
                "detail": d.error_detail,
            }
            server = (
                db.get(Server, project.server_id)
                if (project := d.project_id and db.get(Project, d.project_id))
                else None
            )
            if server is not None and not server.is_local:
                params["server"] = server.name
            kind = "deploy_succeeded" if d.status == "success" else "deploy_failed"
            subject = f"{kind}:{d.project_name}:{deployment_id}"
        self.notifier.emit(Event(kind, subject, params))
