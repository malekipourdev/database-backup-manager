"""The bot's projects menu: list, details, recent deploys, and deploys confirmed with a code."""

import logging

from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.bots.api import BotApiError, Keyboard
from mbp.bots.texts import t
from mbp.models import Deployment
from mbp.projects.service import ProjectService
from mbp.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)

PROJECT_PAGE_SIZE = 8
HISTORY_SIZE = 8
STATUS_ICONS = {"queued": "🕓", "running": "⏳", "success": "✅", "failed": "❌"}


class ProjectMenu:
    """Mixed into BotHandler, next to ContainerMenu (whose code confirmation it uses)."""

    def _init_projects(self, deploy_runner) -> None:
        self.deploy_runner_provider = deploy_runner

    def _deployment_line(self, ctx, d: Deployment) -> str:
        icon = STATUS_ICONS.get(d.status, "•")
        commit = (d.commit_sha or "")[:8] or d.ref
        line = f"{icon} {commit} — {self._time(ctx, d.requested_at)} — {d.actor}"
        if d.status == "failed" and d.error_code:
            line += f"\n   {self._error(ctx, d.error_code)}"
            if d.error_detail:
                line += f": {d.error_detail[:120]}"
        elif d.status in ("queued", "running") and d.step:
            line += f" ({t(ctx.lang, f'step_{d.step}')})"
        return line

    def projects_list(self, db: Session, ctx, page: int, server_id: int = 0):
        """The projects, of every server or (with `server_id`) of one."""
        from mbp.bots.handler import Screen, button

        lang = ctx.lang
        repo = ProjectRepository(db)
        server = self._server(db, server_id) if server_id else None
        projects = repo.list_all(server.id if server else None)
        last = repo.last_deployments()
        keyboard: Keyboard = []
        for project in projects[page * PROJECT_PAGE_SIZE : (page + 1) * PROJECT_PAGE_SIZE]:
            d = last.get(project.id)
            icon = STATUS_ICONS.get(d.status, "⚪️") if d else "⚪️"
            keyboard.append([button(f"{icon} {project.name}", f"p:{project.id}")])
        pager = self._pager(ctx, "pl", page, len(projects), PROJECT_PAGE_SIZE)
        if pager:
            for item in pager:
                item["callback_data"] += f":{server_id}"
            keyboard.append(pager)
        if server:
            keyboard.append(
                [button(t(lang, "btn_back"), f"sh:{server.id}"), button(t(lang, "btn_menu"), "m")]
            )
            text = t(lang, "projects_title_server", server=server.name, n=len(projects))
        else:
            keyboard.append([button(t(lang, "btn_menu"), "m")])
            text = t(lang, "projects_title", n=len(projects))
        if not projects:
            text += "\n\n" + t(lang, "projects_empty")
        return Screen(text, keyboard)

    def project_view(self, db: Session, ctx, project_id: int, note: str | None = None):
        from mbp.bots.handler import Screen, button

        lang = ctx.lang
        project = ProjectService(db).get(project_id)
        repo = ProjectRepository(db)
        last = repo.last_deployments().get(project.id)
        lines = [
            t(lang, "project_title", name=project.name),
            t(lang, "project_repo", repo=project.repo_url),
            t(lang, "project_branch", branch=project.branch),
        ]
        if project.backup_instance_id and project.backup_databases:
            lines.append(t(lang, "project_backup", names=", ".join(project.backup_databases)))
        if last:
            lines.append("")
            lines.append(t(lang, "project_last"))
            lines.append(self._deployment_line(ctx, last))
            if last.commit_message:
                lines.append(f"   {last.commit_message[:120]}")
        else:
            lines.append(t(lang, "project_never"))
        keyboard: Keyboard = [
            [button(t(lang, "btn_deploy", branch=project.branch), f"pd:{project.id}")],
            [
                button(t(lang, "btn_project_history"), f"ph:{project.id}"),
                button(t(lang, "btn_refresh"), f"p:{project.id}"),
            ],
            [button(t(lang, "btn_back"), "pl:0"), button(t(lang, "btn_menu"), "m")],
        ]
        text = "\n".join(lines)
        if note:
            text = f"{note}\n\n{text}"
        return Screen(text, keyboard)

    def project_history(self, db: Session, ctx, project_id: int):
        from mbp.bots.handler import Screen, button

        project = ProjectService(db).get(project_id)
        items, _ = ProjectRepository(db).deployments_page(project.id, 1, HISTORY_SIZE)
        lines = [t(ctx.lang, "project_history", name=project.name)]
        lines += [self._deployment_line(ctx, d) for d in items] or [t(ctx.lang, "project_never")]
        return Screen(
            "\n".join(lines),
            [[button(t(ctx.lang, "btn_back"), f"p:{project.id}")]],
        )

    def ask_deploy(self, db: Session, ctx, project_id: int, chat_id: int):
        from mbp.bots.handler import Screen, button

        lang = ctx.lang
        project = ProjectService(db).get(project_id)
        back = [[button(t(lang, "btn_back"), f"p:{project.id}")]]
        if ProjectRepository(db).active_deployment(project.id) is not None:
            raise ApiError(409, "deploy_in_progress")
        refused = self._code_prerequisites(db, ctx, back)
        if refused is not None:
            return refused
        self._set_pending(chat_id, ctx, str(project.id), "deploy")
        return Screen(
            t(lang, "confirm_deploy", name=project.name, branch=project.branch),
            [[button(t(lang, "btn_cancel"), f"pdx:{project.id}")]],
        )

    def cancel_deploy(self, db: Session, ctx, project_id: int, chat_id: int):
        with self._pending_lock:
            self._pending.pop(chat_id, None)
        return self.project_view(db, ctx, project_id, note=t(ctx.lang, "action_cancelled"))

    def deploy_confirmed(self, db: Session, ctx, project_id: int, actor: str, chat_id: int):
        """Called by the code confirmation once a valid code arrived."""
        from mbp.bots.handler import Screen, button

        runner = self.deploy_runner_provider() if self.deploy_runner_provider else None
        if runner is None:
            raise ApiError(503, "agent_unreachable")
        service = ProjectService(db)
        project = service.get(project_id)
        deployment = service.request_deploy(project, ref=None, trigger=self.platform, actor=actor)
        lang = ctx.lang

        def done(deployment_id: int) -> None:
            with self.session_factory() as session:
                d = session.get(Deployment, deployment_id)
                if d is None:
                    return
                key = "deploy_done" if d.status == "success" else "deploy_failed_msg"
                text = t(
                    lang,
                    key,
                    name=d.project_name,
                    commit=(d.commit_sha or "")[:8],
                    error=self._error(ctx, d.error_code or "error"),
                )
                if d.status == "failed" and d.error_detail:
                    text += f"\n{d.error_detail[:200]}"
            try:
                self.api.send_message(
                    chat_id, text, [[button(t(lang, "btn_view_project"), f"p:{project_id}")]]
                )
            except BotApiError:
                logger.warning("%s bot: could not send the deploy result", self.platform)

        runner.submit(deployment.id, on_done=done)
        return Screen(
            t(lang, "deploy_started", name=project.name, branch=project.branch),
            [[button(t(lang, "btn_view_project"), f"p:{project.id}")]],
        )
