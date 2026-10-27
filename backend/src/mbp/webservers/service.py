"""Rules on top of the agent's web server operations: read-only mode and the audit log."""

import logging
import re
from collections.abc import Callable

from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.containers.agent_client import AgentClient
from mbp.db import utcnow
from mbp.models import Server, WebAction, WebServerSettings
from mbp.repositories.webserver_repository import WebServerRepository

logger = logging.getLogger(__name__)

JOB_RE = re.compile(r"[0-9a-f]{32}")
MAX_OUTPUT = 20_000


class WebServerService:
    """One server's web servers, through its agent."""

    def __init__(self, db: Session, agent: AgentClient, server: Server) -> None:
        self.db = db
        self.agent = agent
        self.server_id = server.id
        self.server_name = server.name
        self.repo = WebServerRepository(db)

    @property
    def settings(self) -> WebServerSettings:
        return self.repo.get_settings(self.server_id)

    # --- reads ---

    def list(self) -> dict:
        return self.agent.webservers()

    def status(self) -> dict:
        status = self.agent.web_status()
        for item in status["servers"]:
            last = self.repo.last_action(self.server_id, item["kind"], ("reload", "restart"))
            item["panel_reload"] = last.created_at if last else None
        return status

    # --- changes ---

    def change(
        self,
        kind: str,
        action: str,
        target: str,
        call: Callable[[], dict],
        *,
        actor: str,
        source: str = "panel",
    ) -> dict:
        """Runs a change unless the server is read-only; every attempt is audited."""
        try:
            if self.settings.read_only:
                raise ApiError(403, "webservers_read_only")
            result = call()
        except ApiError as exc:
            self._audit(actor, source, kind, action, target, exc.code, exc.detail)
            raise
        if "job_id" in result:
            self._audit(actor, source, kind, action, target, "running", None, result["job_id"])
        else:
            outcome = "ok" if result.get("ok") else (result.get("code") or "failed")
            self._audit(actor, source, kind, action, target, outcome, result.get("output"))
            logger.info(
                "%s (%s) %s %s %s on %s: %s",
                actor,
                source,
                action,
                kind,
                target,
                self.server_name,
                outcome,
            )
        return result

    def job(self, job_id: str) -> dict:
        if not JOB_RE.fullmatch(job_id):
            raise ApiError(404, "job_not_found")
        row = self.repo.action_by_job(self.server_id, job_id)
        if row is None:
            raise ApiError(404, "job_not_found")
        view = self.agent.web_job(job_id)
        if view["status"] != "running" and row.result == "running":
            row.result = "ok" if view["status"] == "success" else "failed"
            row.output = (view.get("output") or "")[-MAX_OUTPUT:] or None
            self.db.commit()
        return view

    def start_job(
        self, kind: str, action: str, target: str, call: Callable[[], dict], *, actor: str
    ) -> dict:
        def run() -> dict:
            view = call()
            return {**view, "job_id": view["id"]}

        return self.change(kind, action, target, run, actor=actor)

    def _audit(
        self,
        actor: str,
        source: str,
        kind: str,
        action: str,
        target: str,
        result: str,
        output: str | None,
        job_id: str | None = None,
    ) -> None:
        self.repo.add_action(
            WebAction(
                created_at=utcnow(),
                actor=actor[:100],
                source=source,
                server_id=self.server_id,
                server_name=self.server_name[:60],
                kind=kind,
                action=action,
                target=target[:500],
                result=result[:64],
                output=(output or None) and output[-MAX_OUTPUT:],
                job_id=job_id,
            )
        )
        self.db.commit()


def ensure_project_site(
    db: Session,
    agent: AgentClient,
    server: Server,
    domains: list[str],
    target: str,
    *,
    actor: str,
) -> str:
    """After a deploy: a reverse proxy for a project's domains, unless a site has them.

    Returns a line for the deploy log; never raises (the deploy itself succeeded).
    """
    try:
        found = agent.webservers()
        servers = found.get("servers") or []
        taken = {
            name
            for ws in servers
            for site in ws["sites"]
            if site.get("enabled")
            for name in site["names"]
        }
        missing = [d for d in domains if d not in taken]
        if not missing:
            return f"Web server: {', '.join(domains)} already configured."
        domains = missing
        kinds = [ws["kind"] for ws in servers if not ws.get("error")]
        if not kinds:
            return "Web server: no nginx or Apache on this server; domains not configured."
        kind = "nginx" if "nginx" in kinds else kinds[0]
        spec = {"template": "proxy", "domains": domains, "target": target}
        service = WebServerService(db, agent, server)
        result = service.change(
            kind,
            "create",
            " ".join(domains),
            lambda: agent.web_create(kind, spec),
            actor=actor,
            source="deploy",
        )
    except ApiError as exc:
        return f"⚠ Web server: could not configure {', '.join(domains)} ({exc.code})."
    if not result.get("ok"):
        return f"⚠ Web server: {kind} refused the new site ({result.get('code')}); nothing changed."
    return f"Web server: {', '.join(domains)} now proxied to {target} ({result.get('path')})."
