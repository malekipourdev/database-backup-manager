"""The bot's containers menu: servers, list, details, logs, server status, confirmed actions.

Viewing is open to every bot admin. Start, stop and restart ask for a fresh Google
Authenticator code of a panel account (two-step verification must be on in the panel), so
a stolen or borrowed messenger account cannot control the server's containers.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mbp.agent.docker import parse_time
from mbp.api.errors import ApiError
from mbp.bots.api import Keyboard
from mbp.bots.texts import digits, format_size, t
from mbp.containers.service import ContainerService
from mbp.models import AdminAccount, BotAdmin, Server
from mbp.repositories.container_repository import ContainerRepository
from mbp.repositories.server_repository import ServerRepository
from mbp.security import crypto, totp

logger = logging.getLogger(__name__)

CONTAINER_PAGE_SIZE = 8
LOG_LINES = 30
# Telegram messages hold 4096 characters; leave room for the title.
LOG_CHARS = 3500
CODE_TTL_SECONDS = 120
CODE_TRIES = 3
# Wrong codes per bot admin before container control from the bot is blocked.
MAX_FAILURES = 5
FAILURE_WINDOW_SECONDS = 15 * 60
CODE_RE = re.compile(r"\d{6}")
ICONS = {
    "running": "🟢",
    "exited": "⚪️",
    "created": "⚪️",
    "paused": "⏸",
    "restarting": "🔴",
    "dead": "🔴",
}


@dataclass
class PendingAction:
    bot_admin_id: int
    name: str
    action: str
    expires: float
    tries: int = 0
    server_id: int = 0


def _icon(container: dict) -> str:
    if container.get("problem") in ("crashed", "restarting"):
        return "🔴"
    if container.get("problem") == "unhealthy":
        return "🟠"
    return ICONS.get(container.get("state", ""), "⚪️")


def _order(container: dict) -> tuple:
    return (
        container.get("problem") is None,
        container.get("state") != "running",
        container["name"],
    )


def _percent(value: float | None, lang: str) -> str:
    return digits(f"{value:.0f}", lang) if value is not None else "—"


class ContainerMenu:
    """Mixed into BotHandler; uses its api, platform, clock, _token and helpers."""

    def _init_containers(self, agents_provider) -> None:
        # Returns the app's AgentRegistry (or None).
        self.agents_provider = agents_provider
        self._pending: dict[int, PendingAction] = {}
        self._failures: dict[int, list[float]] = {}
        self._pending_lock = threading.Lock()

    def _server(self, db: Session, server_id: int | None) -> Server:
        repo = ServerRepository(db)
        server = repo.get(server_id) if server_id else repo.local()
        if server is None:
            raise ApiError(404, "server_not_found")
        return server

    def _containers(self, db: Session, server_id: int | None) -> ContainerService:
        registry = self.agents_provider() if self.agents_provider else None
        if registry is None:
            raise ApiError(503, "agent_unreachable")
        server = self._server(db, server_id)
        return ContainerService(db, registry.for_server(server), server)

    def _unavailable(self, ctx, exc: ApiError, server_id: int):
        from mbp.bots.handler import Screen, button

        return Screen(
            t(ctx.lang, "containers_unavailable", reason=self._error(ctx, exc.code)),
            [
                [
                    button(t(ctx.lang, "btn_refresh"), f"cl:0:{server_id}"),
                    button(t(ctx.lang, "btn_menu"), "m"),
                ]
            ],
        )

    # --- screens ---

    def servers_list(self, db: Session, ctx):
        """The connected servers; skipped when the panel's own is the only one."""
        from mbp.bots.handler import Screen, button

        servers = [s for s in ServerRepository(db).list_all() if s.paired]
        keyboard: Keyboard = []
        for server in servers:
            icon = "🔴" if server.last_error else "🟢"
            label = f"{icon} {server.name}" + (
                f" ({t(ctx.lang, 'server_local')})" if server.is_local else ""
            )
            keyboard.append([button(label[:60], f"cl:0:{server.id}")])
        keyboard.append([button(t(ctx.lang, "btn_menu"), "m")])
        return Screen(t(ctx.lang, "servers_title", n=len(servers)), keyboard)

    def containers_entry(self, db: Session, ctx, page: int, server_id: int | None):
        if server_id is None:
            servers = [s for s in ServerRepository(db).list_all() if s.paired]
            if len(servers) > 1:
                return self.servers_list(db, ctx)
            server_id = servers[0].id if servers else ServerRepository(db).local().id
        return self.containers_list(db, ctx, page, server_id)

    def containers_list(self, db: Session, ctx, page: int, server_id: int):
        from mbp.bots.handler import Screen, button

        lang = ctx.lang
        try:
            svc = self._containers(db, server_id)
            items = sorted(svc.containers(), key=_order)
        except ApiError as exc:
            return self._unavailable(ctx, exc, server_id)
        multiple = sum(1 for s in ServerRepository(db).list_all() if s.paired) > 1
        running = sum(1 for c in items if c["state"] == "running")
        problems = sum(1 for c in items if c.get("problem"))
        title = t(
            lang,
            "containers_title",
            running=running,
            total=len(items),
            problems=t(lang, "containers_problems", n=problems) if problems else "",
        )
        if multiple:
            title = f"🖥 {svc.server_name}\n{title}"
        keyboard: Keyboard = [
            [button(f"{_icon(c)} {c['name']}"[:60], f"c:{self._token(server_id, c['name'])}")]
            for c in items[page * CONTAINER_PAGE_SIZE : (page + 1) * CONTAINER_PAGE_SIZE]
        ]
        pager = self._pager(ctx, "cl", page, len(items), CONTAINER_PAGE_SIZE)
        if pager:
            for item in pager:
                item["callback_data"] += f":{server_id}"
            keyboard.append(pager)
        keyboard.append(
            [
                button(t(lang, "btn_server"), f"cs:{server_id}"),
                button(t(lang, "btn_refresh"), f"cl:{page}:{server_id}"),
            ]
        )
        if multiple:
            keyboard.append(
                [button(t(lang, "btn_servers"), "sv"), button(t(lang, "btn_menu"), "m")]
            )
        else:
            keyboard.append([button(t(lang, "btn_menu"), "m")])
        text = title if items else f"{title}\n\n{t(lang, 'containers_empty')}"
        return Screen(text, keyboard)

    def server_status(self, db: Session, ctx, server_id: int):
        from mbp.bots.handler import Screen, button

        lang = ctx.lang
        try:
            info = self._containers(db, server_id).info()
        except ApiError as exc:
            return self._unavailable(ctx, exc, server_id)
        docker, host = info["docker"], info["host"]
        lines = [
            t(lang, "server_title", name=docker.get("name") or ""),
            t(
                lang,
                "server_docker",
                version=docker.get("version") or "?",
                running=docker.get("running") or 0,
                stopped=docker.get("stopped") or 0,
                images=docker.get("images") or 0,
            ),
        ]
        load = host.get("load") or []
        lines.append(
            t(
                lang,
                "server_cpu",
                percent=_percent(host.get("cpu_percent"), lang),
                cpus=docker.get("cpus") or "?",
                load=digits(f"{load[0]:.2f}", lang) if load else "—",
            )
        )
        for key, total, free in (
            ("server_memory", host.get("memory_total"), host.get("memory_available")),
            ("server_disk", host.get("disk_total"), host.get("disk_free")),
        ):
            if total and free is not None:
                used = total - free
                lines.append(
                    t(
                        lang,
                        key,
                        used=format_size(used, lang),
                        total=format_size(total, lang),
                        percent=_percent(used * 100 / total, lang),
                    )
                )
        return Screen(
            "\n".join(lines),
            [
                [
                    button(t(lang, "btn_refresh"), f"cs:{server_id}"),
                    button(t(lang, "btn_back"), f"cl:0:{server_id}"),
                ],
                [button(t(lang, "btn_menu"), "m")],
            ],
        )

    def container_view(self, db: Session, ctx, token: str, note: str | None = None):
        from mbp.bots.handler import Screen, button

        resolved = self._resolve(token)
        if not resolved or len(resolved) != 2:
            return Screen(t(ctx.lang, "expired_button"), self._home(ctx))
        server_id, name = resolved
        lang = ctx.lang
        try:
            svc = self._containers(db, server_id)
            c = svc.container(name)
            usage = svc.agent.container_stats(name) if c["state"] == "running" else None
        except ApiError as exc:
            if exc.code == "container_not_found":
                return Screen(
                    t(lang, "error", message=self._error(ctx, exc.code)),
                    [[button(t(lang, "btn_back"), f"cl:0:{server_id}")]],
                )
            return self._unavailable(ctx, exc, server_id)
        settings = svc.settings
        lines = [
            t(lang, "container_title", name=c["name"]),
            t(lang, "container_image", image=c["image"]),
        ]
        if c.get("project"):
            project = c["project"] + (f" / {c['service']}" if c.get("service") else "")
            lines.append(t(lang, "container_project", project=project))
        state = t(lang, f"state_{'crashed' if c.get('problem') == 'crashed' else c['state']}")
        extra = []
        if c["state"] == "running" and c.get("started_at"):
            extra.append(t(lang, "container_since", time=self._iso_time(ctx, c["started_at"])))
        elif c["state"] in ("exited", "dead"):
            extra.append(t(lang, "container_exit", code=str(c.get("exit_code"))))
            if c.get("oom_killed"):
                extra.append(t(lang, "container_oom"))
        if extra:
            state += f" ({('، ' if lang == 'fa' else ', ').join(extra)})"
        lines.append(t(lang, "container_state", state=state))
        if c.get("health"):
            lines.append(t(lang, "container_health", health=t(lang, f"health_{c['health']}")))
        if c.get("restart_count"):
            lines.append(t(lang, "container_restarts", n=c["restart_count"]))
        ports = [
            f"{p['public']}→{p['private']}/{p['type']}"
            if p.get("public")
            else f"{p['private']}/{p['type']}"
            for p in c.get("ports") or []
        ]
        if ports:
            lines.append(t(lang, "container_ports", ports=", ".join(ports)))
        if usage:
            lines.append(
                t(
                    lang,
                    "container_usage",
                    cpu=_percent(usage.get("cpu_percent"), lang),
                    memory=format_size(usage.get("memory_usage"), lang),
                    percent=_percent(usage.get("memory_percent"), lang),
                )
            )
        keyboard: Keyboard = []
        controls = []
        if settings.read_only:
            lines.append("\n" + t(lang, "container_read_only"))
        elif c.get("locked"):
            lines.append("\n" + t(lang, "container_locked"))
        else:
            if c["state"] == "running":
                controls = [
                    button(t(lang, "btn_restart"), f"ca:{token}:restart"),
                    button(t(lang, "btn_stop"), f"ca:{token}:stop"),
                ]
            else:
                controls = [button(t(lang, "btn_start"), f"ca:{token}:start")]
        if controls:
            keyboard.append(controls)
        keyboard.append(
            [
                button(t(lang, "btn_logs"), f"cg:{token}"),
                button(t(lang, "btn_refresh"), f"c:{token}"),
            ]
        )
        keyboard.append(
            [button(t(lang, "btn_back"), f"cl:0:{server_id}"), button(t(lang, "btn_menu"), "m")]
        )
        text = "\n".join(lines)
        if note:
            text = f"{note}\n\n{text}"
        return Screen(text, keyboard)

    def _iso_time(self, ctx, value: str) -> str:
        parsed = parse_time(value)
        return self._time(ctx, parsed) if parsed else value

    def container_logs(self, db: Session, ctx, token: str):
        from mbp.bots.handler import Screen, button

        resolved = self._resolve(token)
        if not resolved or len(resolved) != 2:
            return Screen(t(ctx.lang, "expired_button"), self._home(ctx))
        server_id, name = resolved
        lang = ctx.lang
        back = [
            [
                button(t(lang, "btn_back"), f"c:{token}"),
                button(t(lang, "btn_refresh"), f"cg:{token}"),
            ]
        ]
        if not ContainerRepository(db).get_settings(server_id).bot_logs:
            return Screen(t(lang, "logs_disabled"), [[button(t(lang, "btn_back"), f"c:{token}")]])
        try:
            lines = self._containers(db, server_id).logs(name, LOG_LINES)["lines"]
        except ApiError as exc:
            return Screen(t(lang, "error", message=self._error(ctx, exc.code)), back)
        if not lines:
            return Screen(t(lang, "logs_empty", name=name), back)
        body = "\n".join(
            ("! " if line["stream"] == "stderr" else "") + line["text"] for line in lines
        )
        if len(body) > LOG_CHARS:
            body = "…" + body[-LOG_CHARS:]
        return Screen(f"{t(lang, 'logs_title', n=len(lines), name=name)}\n\n{body}", back)

    # --- confirmed actions ---

    def _blocked(self, bot_admin_id: int) -> bool:
        now = time.monotonic()
        with self._pending_lock:
            recent = [
                f for f in self._failures.get(bot_admin_id, []) if now - f < FAILURE_WINDOW_SECONDS
            ]
            self._failures[bot_admin_id] = recent
            return len(recent) >= MAX_FAILURES

    def ask_action(self, db: Session, ctx, token: str, action: str, chat_id: int):
        from mbp.bots.handler import Screen, button

        resolved = self._resolve(token)
        if not resolved or len(resolved) != 2 or action not in ("start", "stop", "restart"):
            return Screen(t(ctx.lang, "expired_button"), self._home(ctx))
        server_id, name = resolved
        lang = ctx.lang
        back = [[button(t(lang, "btn_back"), f"c:{token}")]]
        svc = self._containers(db, server_id)
        if svc.settings.read_only:
            raise ApiError(403, "containers_read_only")
        if svc.locked(svc.container(name)):
            raise ApiError(403, "container_locked")
        refused = self._code_prerequisites(db, ctx, back)
        if refused is not None:
            return refused
        self._set_pending(chat_id, ctx, name, action, server_id)
        return Screen(
            t(lang, "confirm_code", action=t(lang, f"action_{action}"), name=name),
            [[button(t(lang, "btn_cancel"), f"cx:{token}")]],
        )

    def _code_prerequisites(self, db: Session, ctx, back):
        """A refusal screen when an action cannot be confirmed with a code, else None."""
        from mbp.bots.handler import Screen

        has_2fa = db.scalar(
            select(AdminAccount.id).where(AdminAccount.totp_enabled.is_(True)).limit(1)
        )
        if has_2fa is None:
            return Screen(t(ctx.lang, "need_2fa"), back)
        if self._blocked(ctx.admin_id):
            return Screen(t(ctx.lang, "code_locked"), back)
        return None

    def _set_pending(self, chat_id: int, ctx, name: str, action: str, server_id: int = 0) -> None:
        with self._pending_lock:
            self._pending[chat_id] = PendingAction(
                ctx.admin_id,
                name,
                action,
                time.monotonic() + CODE_TTL_SECONDS,
                server_id=server_id,
            )

    def cancel_action(self, db: Session, ctx, token: str, chat_id: int):
        with self._pending_lock:
            self._pending.pop(chat_id, None)
        return self.container_view(db, ctx, token, note=t(ctx.lang, "action_cancelled"))

    def pending_action(self, chat_id: int) -> PendingAction | None:
        with self._pending_lock:
            return self._pending.get(chat_id)

    def _verify_code(self, db: Session, code: str) -> AdminAccount | None:
        """A fresh TOTP code of a panel account with two-step verification on."""
        if not CODE_RE.fullmatch(code):
            return None
        now = self.clock().timestamp()
        for account in db.scalars(select(AdminAccount).where(AdminAccount.totp_enabled.is_(True))):
            if not account.totp_secret_encrypted:
                continue
            secret = crypto.decrypt(account.totp_secret_encrypted)
            step = totp.verify(secret, code, account.totp_last_step, now)
            if step is not None:
                account.totp_last_step = step  # a code works once, here and in the panel
                return account
        return None

    def answer_code(self, db: Session, ctx, chat_id: int, text: str):
        """The admin's reply while an action waits for its code."""
        from mbp.bots.handler import Screen, button

        lang = ctx.lang
        with self._pending_lock:
            pending = self._pending.get(chat_id)
        if pending is None or pending.bot_admin_id != ctx.admin_id:
            return None
        if pending.action == "deploy":
            back, cancel = f"p:{pending.name}", f"pdx:{pending.name}"
        else:
            token = self._token(pending.server_id, pending.name)
            back, cancel = f"c:{token}", f"cx:{token}"
        if time.monotonic() > pending.expires:
            with self._pending_lock:
                self._pending.pop(chat_id, None)
            return Screen(t(lang, "code_expired"), [[button(t(lang, "btn_back"), back)]])
        code = re.sub(r"\s", "", text)
        if not CODE_RE.fullmatch(code):
            # Anything else cancels the request and continues as a normal message.
            with self._pending_lock:
                self._pending.pop(chat_id, None)
            return None
        account = self._verify_code(db, code)
        if account is None:
            pending.tries += 1
            with self._pending_lock:
                self._failures.setdefault(ctx.admin_id, []).append(time.monotonic())
            logger.warning("%s bot: wrong action code from admin %s", self.platform, ctx.admin_id)
            if pending.tries >= CODE_TRIES or self._blocked(ctx.admin_id):
                with self._pending_lock:
                    self._pending.pop(chat_id, None)
                key = "code_locked" if self._blocked(ctx.admin_id) else "code_expired"
                return Screen(t(lang, key), [[button(t(lang, "btn_back"), back)]])
            return Screen(
                t(lang, "code_wrong", left=CODE_TRIES - pending.tries),
                [[button(t(lang, "btn_cancel"), cancel)]],
            )
        with self._pending_lock:
            self._pending.pop(chat_id, None)
        db.commit()  # the code is spent even if the action fails
        bot_admin = db.get(BotAdmin, ctx.admin_id)
        actor = f"{bot_admin.display_name if bot_admin else ctx.admin_id} ({account.username})"
        if pending.action == "deploy":
            return self.deploy_confirmed(db, ctx, int(pending.name), actor, chat_id)
        try:
            self._containers(db, pending.server_id).act(
                pending.name, pending.action, actor=actor, source=self.platform
            )
        except ApiError as exc:
            return Screen(
                t(lang, "error", message=self._error(ctx, exc.code)),
                [[button(t(lang, "btn_back"), back)]],
            )
        done = t(lang, "action_done", action=t(lang, f"action_{pending.action}"), name=pending.name)
        return self.container_view(db, ctx, token, note=done)
