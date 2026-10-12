"""Answers bot updates: menus with inline buttons, for registered admins only.

Every message and button press is checked against the admins registered in the panel.
Anyone else gets their own numeric ID and nothing more. Destructive actions ask for
confirmation. Secrets (database passwords, storage keys) can never be entered or shown here.
"""

import logging
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from mbp.api.errors import ApiError
from mbp.api.schemas import ScheduleIn
from mbp.backups.store import LocalBackupStore
from mbp.bots.api import BotApi, BotApiError, Keyboard
from mbp.bots.containers import ContainerMenu
from mbp.bots.projects import ProjectMenu
from mbp.bots.texts import format_duration, format_size, format_time, t
from mbp.db import utcnow
from mbp.models import BackupRun, BotAdmin
from mbp.repositories.backup_run_repository import BackupRunRepository, RunFilters
from mbp.repositories.bot_repository import BotRepository
from mbp.repositories.notification_repository import NotificationRepository
from mbp.repositories.remote_storage_repository import RemoteStorageRepository
from mbp.repositories.selection_repository import SelectionRepository
from mbp.services.backup_service import BackupService
from mbp.services.bot_service import BotService
from mbp.services.instance_service import InstanceService
from mbp.services.mysql_probe import ProbeResult
from mbp.services.remote_storage_service import is_configured
from mbp.services.retention_service import RetentionService, global_retention
from mbp.services.schedule_service import ScheduleService, next_run_at
from mbp.services.selection_service import SelectionService

logger = logging.getLogger(__name__)

PAGE_SIZE = 8
DB_PAGE_SIZE = 10
TOKEN_TTL_SECONDS = 3600
PREVIEW_LIMIT = 15
LEVELS = ("info", "warning", "error", "off")
# What a link code looks like (see services.bot_service); anything else is not a code.
LINK_CODE_RE = re.compile(r"[A-Za-z0-9]{8}")
STATUS_ICONS = {"queued": "🕓", "running": "⏳", "success": "✅", "failed": "❌"}


@dataclass
class Screen:
    text: str
    keyboard: Keyboard


@dataclass
class Ctx:
    lang: str
    admin_id: int
    zone: ZoneInfo


def button(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


class BotHandler(ContainerMenu, ProjectMenu):
    def __init__(
        self,
        platform: str,
        api: BotApi,
        session_factory: sessionmaker[Session],
        runner,
        store: LocalBackupStore,
        *,
        scheduler=None,
        agent=None,
        deploy_runner=None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.platform = platform
        self.api = api
        self.session_factory = session_factory
        self.runner = runner
        self.store = store
        self.scheduler = scheduler
        self.clock = clock
        # Short tokens for callback data that would not fit Telegram's 64-byte limit
        # (database names can be 64 characters, i.e. up to 256 bytes).
        self._tokens: dict[str, tuple[float, tuple]] = {}
        self._lock = threading.Lock()
        # `agent` returns the app's AgentRegistry (or None).
        self._init_containers(agent)
        # `deploy_runner` returns the app's DeployRunner (or None).
        self._init_projects(deploy_runner)

    # --- entry points ---

    def handle_update(self, update: dict) -> None:
        try:
            if "callback_query" in update:
                self._on_callback(update["callback_query"])
            elif "message" in update:
                self._on_message(update["message"])
        except BotApiError as exc:
            logger.warning("%s bot could not answer: %s", self.platform, exc.code)
        except Exception:
            logger.exception("%s bot failed to handle an update", self.platform)

    def _admin(self, db: Session, user_id: int | None) -> BotAdmin | None:
        if user_id is None:
            return None
        admin = BotRepository(db).admin_by_user(self.platform, int(user_id))
        if admin is None or not admin.enabled:
            return None
        admin.last_seen_at = self.clock()
        return admin

    def _ctx(self, db: Session, admin: BotAdmin) -> Ctx:
        zone_name = NotificationRepository(db).get_settings().timezone
        try:
            zone = ZoneInfo(zone_name)
        except Exception:
            zone = ZoneInfo("UTC")
        return Ctx(lang=admin.language, admin_id=admin.id, zone=zone)

    def _on_message(self, message: dict) -> None:
        chat = message.get("chat") or {}
        # Group chats are ignored: anyone in a group could press the buttons.
        if chat.get("type", "private") != "private":
            return
        user_id = (message.get("from") or {}).get("id")
        chat_id = chat.get("id", user_id)
        text = (message.get("text") or "").strip()
        with self.session_factory() as db:
            admin = self._admin(db, user_id)
            if admin is None:
                code = text.split()[-1] if text.startswith("/start ") else text
                linked = None
                if LINK_CODE_RE.fullmatch(code) and user_id is not None:
                    linked = BotService(db).consume_link_code(self.platform, code, int(user_id))
                    if linked is None:
                        self.api.send_message(chat_id, t("fa", "link_invalid"))
                        return
                if linked is None:
                    self.api.send_message(chat_id, t("fa", "unauthorized", user_id=str(user_id)))
                    return
                logger.info("%s bot: user %s linked as admin", self.platform, user_id)
                self.api.send_message(
                    chat_id, t(linked.language, "linked", name=linked.display_name)
                )
                admin = linked
            ctx = self._ctx(db, admin)
            screen = None
            if self.pending_action(chat_id) is not None:
                try:
                    screen = self.answer_code(db, ctx, chat_id, text)
                except ApiError as exc:
                    screen = Screen(
                        t(ctx.lang, "error", message=self._error(ctx, exc.code)), self._home(ctx)
                    )
            if screen is None:
                screen = self.status(db, ctx) if text.startswith("/status") else self.menu(ctx)
            db.commit()
        self.api.send_message(chat_id, screen.text, screen.keyboard)

    def _on_callback(self, query: dict) -> None:
        message = query.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type", "private") != "private":
            self.api.answer_callback(query.get("id", ""))
            return
        user_id = (query.get("from") or {}).get("id")
        chat_id = chat.get("id", user_id)
        message_id = message.get("message_id")
        data = query.get("data") or ""
        with self.session_factory() as db:
            admin = self._admin(db, user_id)
            if admin is None:
                self.api.answer_callback(query.get("id", ""), t("fa", "unauthorized_short"))
                return
            ctx = self._ctx(db, admin)
            db.commit()
        self.api.answer_callback(query.get("id", ""))
        logger.info("%s bot: admin %s pressed %s", self.platform, ctx.admin_id, data)
        with self.session_factory() as db:
            try:
                screen = self.route(db, ctx, data, chat_id)
            except ApiError as exc:
                screen = Screen(
                    t(ctx.lang, "error", message=self._error(ctx, exc.code)), self._home(ctx)
                )
            db.commit()
        if screen is None:
            return
        try:
            if message_id is None:
                raise BotApiError("no_message")
            self.api.edit_message(chat_id, message_id, screen.text, screen.keyboard)
        except BotApiError:
            self.api.send_message(chat_id, screen.text, screen.keyboard)

    # --- routing ---

    def route(self, db: Session, ctx: Ctx, data: str, chat_id: int) -> Screen | None:
        parts = data.split(":")
        head, args = parts[0], parts[1:]

        def num(index: int, default: int = 0) -> int:
            try:
                return int(args[index])
            except (IndexError, ValueError):
                return default

        routes: dict[str, Callable[[], Screen | None]] = {
            "m": lambda: self.menu(ctx),
            "st": lambda: self.status(db, ctx),
            "il": lambda: self.instances(db, ctx, num(0)),
            "i": lambda: self.instance(db, ctx, num(0)),
            "it": lambda: self.test_instance(db, ctx, num(0)),
            "ba": lambda: self.confirm_backup_all(db, ctx, num(0)),
            "bac": lambda: self.backup_all(db, ctx, num(0)),
            "dl": lambda: self.databases(db, ctx, num(0), num(1)),
            "bo": lambda: self.backup_one(db, ctx, args[0] if args else ""),
            "rl": lambda: self.runs(db, ctx, num(0), num(1)),
            "r": lambda: self.run(db, ctx, num(0)),
            "rf": lambda: self.send_file(db, ctx, num(0), chat_id),
            "ru": lambda: self.upload(db, ctx, num(0)),
            "rd": lambda: self.confirm_delete(db, ctx, num(0)),
            "rdc": lambda: self.delete(db, ctx, num(0), remote=num(1) == 1),
            "sl": lambda: self.schedules(db, ctx, num(0)),
            "s": lambda: self.schedule(db, ctx, num(0)),
            "se": lambda: self.toggle_schedule(db, ctx, num(0)),
            "sr": lambda: self.run_schedule(db, ctx, num(0)),
            "rt": lambda: self.retention(db, ctx),
            "rtp": lambda: self.retention_preview(db, ctx),
            "rta": lambda: self.retention_apply(db, ctx),
            "ns": lambda: self.settings(db, ctx),
            "nl": lambda: self.set_level(db, ctx, args[0] if args else ""),
            "lg": lambda: self.toggle_language(db, ctx),
            "sv": lambda: self.servers_list(db, ctx),
            "cl": lambda: self.containers_entry(db, ctx, num(0), num(1) if len(args) > 1 else None),
            "cs": lambda: self.server_status(db, ctx, num(0)),
            "c": lambda: self.container_view(db, ctx, args[0] if args else ""),
            "cg": lambda: self.container_logs(db, ctx, args[0] if args else ""),
            "ca": lambda: self.ask_action(
                db, ctx, args[0] if args else "", args[1] if len(args) > 1 else "", chat_id
            ),
            "cx": lambda: self.cancel_action(db, ctx, args[0] if args else "", chat_id),
            "pl": lambda: self.projects_list(db, ctx, num(0)),
            "p": lambda: self.project_view(db, ctx, num(0)),
            "ph": lambda: self.project_history(db, ctx, num(0)),
            "pd": lambda: self.ask_deploy(db, ctx, num(0), chat_id),
            "pdx": lambda: self.cancel_deploy(db, ctx, num(0), chat_id),
        }
        action = routes.get(head)
        if action is None:
            return Screen(t(ctx.lang, "expired_button"), self._home(ctx))
        return action()

    # --- helpers ---

    def _token(self, *value) -> str:
        now = time.monotonic()
        with self._lock:
            for key, (created, _) in list(self._tokens.items()):
                if now - created > TOKEN_TTL_SECONDS:
                    del self._tokens[key]
            token = secrets.token_urlsafe(6)
            self._tokens[token] = (now, value)
        return token

    def _resolve(self, token: str) -> tuple | None:
        with self._lock:
            entry = self._tokens.get(token)
        return entry[1] if entry else None

    def _home(self, ctx: Ctx) -> Keyboard:
        return [[button(t(ctx.lang, "btn_menu"), "m")]]

    def _error(self, ctx: Ctx, code: str) -> str:
        text = t(ctx.lang, f"result_{code}")
        return code if text == f"result_{code}" else text

    def _pager(self, ctx: Ctx, prefix: str, page: int, total: int, size: int) -> list[dict]:
        row = []
        if page > 0:
            row.append(button(t(ctx.lang, "btn_prev"), f"{prefix}:{page - 1}"))
        if (page + 1) * size < total:
            row.append(button(t(ctx.lang, "btn_next"), f"{prefix}:{page + 1}"))
        return row

    def _time(self, ctx: Ctx, value: datetime | None) -> str:
        return format_time(value, ctx.lang, ctx.zone)

    # --- screens ---

    def menu(self, ctx: Ctx) -> Screen:
        lang = ctx.lang
        return Screen(
            t(lang, "menu_title"),
            [
                [button(t(lang, "btn_status"), "st"), button(t(lang, "btn_instances"), "il:0")],
                [button(t(lang, "btn_runs"), "rl:0:0"), button(t(lang, "btn_schedules"), "sl:0")],
                [
                    button(t(lang, "btn_containers"), "cl:0"),
                    button(t(lang, "btn_projects"), "pl:0"),
                ],
                [button(t(lang, "btn_retention"), "rt"), button(t(lang, "btn_settings"), "ns")],
            ],
        )

    def status(self, db: Session, ctx: Ctx) -> Screen:
        lang = ctx.lang
        runs = BackupRunRepository(db)
        instances = InstanceService(db).list()
        since = self.clock().timestamp() - 86400
        recent, _ = runs.query(RunFilters(), page=1, page_size=1000)
        last_day = [r for r in recent if r.finished_at and r.finished_at.timestamp() >= since]
        active = runs.list_active()
        last_ok, _ = runs.query(RunFilters(statuses=["success"]), page=1, page_size=1)
        lines = [
            t(lang, "status_title"),
            "",
            t(lang, "status_instances", n=len(instances)),
            t(lang, "status_active", n=len(active)),
            t(
                lang,
                "status_24h",
                ok=sum(1 for r in last_day if r.status == "success"),
                failed=sum(1 for r in last_day if r.status == "failed"),
            ),
        ]
        if last_ok:
            run = last_ok[0]
            lines.append(
                t(
                    lang,
                    "status_last_ok",
                    db=run.database_name,
                    instance=run.instance_name,
                    time=self._time(ctx, run.finished_at),
                )
            )
        else:
            lines.append(t(lang, "status_last_ok_none"))
        try:
            usage = shutil.disk_usage(self.store.root)
            lines.append(
                t(
                    lang,
                    "status_disk",
                    free=format_size(usage.free, lang),
                    total=format_size(usage.total, lang),
                )
            )
        except OSError:
            pass
        remote = RemoteStorageRepository(db).get()
        if is_configured(remote) and remote.enabled:
            lines.append(t(lang, "status_remote_on", bucket=remote.bucket))
        else:
            lines.append(t(lang, "status_remote_off"))
        upcoming = []
        for schedule in ScheduleService(db).list_all():
            when = next_run_at(schedule)
            if when is not None:
                upcoming.append((when, schedule))
        if upcoming:
            when, schedule = min(upcoming, key=lambda item: item[0])
            name = next((i.name for i in instances if i.id == schedule.instance_id), "")
            lines.append(
                t(
                    lang,
                    "status_next",
                    name=schedule.name,
                    instance=name,
                    time=self._time(ctx, when),
                )
            )
        else:
            lines.append(t(lang, "status_next_none"))
        return Screen(
            "\n".join(lines),
            [[button(t(lang, "btn_refresh"), "st"), button(t(lang, "btn_menu"), "m")]],
        )

    def instances(self, db: Session, ctx: Ctx, page: int) -> Screen:
        items = InstanceService(db).list()
        if not items:
            return Screen(t(ctx.lang, "instances_empty"), self._home(ctx))
        chunk = items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
        keyboard: Keyboard = []
        for instance in chunk:
            kind = (
                f" · {instance.server_type} {instance.server_version}"
                if instance.server_type
                else ""
            )
            keyboard.append([button(f"🖥 {instance.name}{kind}", f"i:{instance.id}")])
        pager = self._pager(ctx, "il", page, len(items), PAGE_SIZE)
        if pager:
            keyboard.append(pager)
        keyboard.append([button(t(ctx.lang, "btn_menu"), "m")])
        return Screen(t(ctx.lang, "instances_title", n=len(items)), keyboard)

    def instance(self, db: Session, ctx: Ctx, instance_id: int) -> Screen:
        lang = ctx.lang
        instance = InstanceService(db).get(instance_id)
        marked = SelectionRepository(db).list_names(instance_id)
        lines = [
            t(lang, "instance_title", name=instance.name),
            t(lang, "instance_address", address=f"{instance.host}:{instance.port}"),
            (
                t(
                    lang,
                    "instance_server",
                    server=f"{instance.server_type} {instance.server_version}",
                )
                if instance.server_type
                else t(lang, "instance_server_unknown")
            ),
        ]
        if marked:
            shown = ", ".join(marked[:10]) + ("…" if len(marked) > 10 else "")
            lines.append(t(lang, "instance_marked", n=len(marked), names=shown))
        else:
            lines.append(t(lang, "instance_marked_none"))
        last, _ = BackupRunRepository(db).query(RunFilters(instance_id=instance_id), page_size=1)
        if last:
            lines.append(
                t(
                    lang,
                    "instance_last_run",
                    status=t(lang, f"status_{last[0].status}"),
                    time=self._time(ctx, last[0].requested_at),
                )
            )
        keyboard: Keyboard = [[button(t(lang, "btn_test"), f"it:{instance_id}")]]
        if marked:
            keyboard.append([button(t(lang, "btn_backup_all", n=len(marked)), f"ba:{instance_id}")])
        keyboard += [
            [button(t(lang, "btn_backup_one"), f"dl:{instance_id}:0")],
            [
                button(t(lang, "btn_instance_runs"), f"rl:{instance_id}:0"),
                button(t(lang, "btn_instance_schedules"), f"sl:{instance_id}"),
            ],
            [button(t(lang, "btn_back"), "il:0"), button(t(lang, "btn_menu"), "m")],
        ]
        return Screen("\n".join(lines), keyboard)

    def test_instance(self, db: Session, ctx: Ctx, instance_id: int) -> Screen:
        result: ProbeResult = InstanceService(db).test_saved(instance_id)
        if result.ok:
            text = t(ctx.lang, "test_ok", server=f"{result.server_type} {result.server_version}")
        else:
            reason = result.error_code or "server_error"
            if result.error_detail:
                reason = f"{reason} — {result.error_detail}"
            text = t(ctx.lang, "test_failed", reason=reason)
        screen = self.instance(db, ctx, instance_id)
        return Screen(f"{text}\n\n{screen.text}", screen.keyboard)

    def confirm_backup_all(self, db: Session, ctx: Ctx, instance_id: int) -> Screen:
        instance = InstanceService(db).get(instance_id)
        names = SelectionRepository(db).list_names(instance_id)
        if not names:
            raise ApiError(422, "no_databases_selected")
        return Screen(
            t(
                ctx.lang,
                "confirm_backup_all",
                n=len(names),
                name=instance.name,
                names="\n".join(names[:20]),
            ),
            [
                [
                    button(t(ctx.lang, "btn_yes"), f"bac:{instance_id}"),
                    button(t(ctx.lang, "btn_cancel"), f"i:{instance_id}"),
                ]
            ],
        )

    def _started(self, ctx: Ctx, instance_id: int, created: list, skipped: list) -> Screen:
        lines = [t(ctx.lang, "backup_started", n=len(created))]
        if skipped:
            lines.append(
                t(ctx.lang, "backup_skipped", names=", ".join(s["database"] for s in skipped))
            )
        return Screen(
            "\n".join(lines),
            [
                [button(t(ctx.lang, "btn_instance_runs"), f"rl:{instance_id}:0")],
                [
                    button(t(ctx.lang, "btn_back"), f"i:{instance_id}"),
                    button(t(ctx.lang, "btn_menu"), "m"),
                ],
            ],
        )

    def backup_all(self, db: Session, ctx: Ctx, instance_id: int) -> Screen:
        created, skipped = BackupService(db, self.runner, self.store).start(
            instance_id, "all", None
        )
        logger.info(
            "%s bot: admin %s started backups of instance %s",
            self.platform,
            ctx.admin_id,
            instance_id,
        )
        return self._started(ctx, instance_id, created, skipped)

    def databases(self, db: Session, ctx: Ctx, instance_id: int, page: int) -> Screen:
        instance = InstanceService(db).get(instance_id)
        listing = SelectionService(db).get_listing(instance_id)
        back = [
            button(t(ctx.lang, "btn_back"), f"i:{instance_id}"),
            button(t(ctx.lang, "btn_menu"), "m"),
        ]
        if not listing.reachable:
            reason = listing.error_code or "server_error"
            return Screen(t(ctx.lang, "databases_unreachable", reason=reason), [back])
        entries = [entry for entry in listing.databases if entry.selectable and not entry.missing]
        if not entries:
            return Screen(t(ctx.lang, "databases_empty"), [back])
        chunk = entries[page * DB_PAGE_SIZE : (page + 1) * DB_PAGE_SIZE]
        keyboard: Keyboard = []
        row: list[dict] = []
        for entry in chunk:
            label = f"✅ {entry.name}" if entry.selected else entry.name
            row.append(button(label, f"bo:{self._token(instance_id, entry.name)}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        pager = self._pager(ctx, f"dl:{instance_id}", page, len(entries), DB_PAGE_SIZE)
        if pager:
            keyboard.append(pager)
        keyboard.append(back)
        return Screen(t(ctx.lang, "databases_title", name=instance.name), keyboard)

    def backup_one(self, db: Session, ctx: Ctx, token: str) -> Screen:
        value = self._resolve(token)
        if value is None:
            return Screen(t(ctx.lang, "expired_button"), self._home(ctx))
        instance_id, database = value
        created, skipped = BackupService(db, self.runner, self.store).start(
            instance_id, "single", database
        )
        logger.info(
            "%s bot: admin %s started a backup of %s on instance %s",
            self.platform,
            ctx.admin_id,
            database,
            instance_id,
        )
        return self._started(ctx, instance_id, created, skipped)

    def runs(self, db: Session, ctx: Ctx, instance_id: int, page: int) -> Screen:
        lang = ctx.lang
        filters = RunFilters(instance_id=instance_id or None)
        items, total = BackupRunRepository(db).query(filters, page=page + 1, page_size=PAGE_SIZE)
        scope = ""
        if instance_id:
            scope = t(lang, "runs_scope", name=InstanceService(db).get(instance_id).name)
        back_target = f"i:{instance_id}" if instance_id else "m"
        if not items:
            return Screen(
                t(lang, "runs_empty"),
                [[button(t(lang, "btn_back"), back_target), button(t(lang, "btn_menu"), "m")]],
            )
        keyboard: Keyboard = []
        for run in items:
            icon = STATUS_ICONS.get(run.status, "")
            remote = " ☁️" if run.has_remote_copy else ""
            size = f" · {format_size(run.file_size, lang)}" if run.file_size else ""
            label = f"{icon} {run.database_name}{'' if instance_id else ' @ ' + run.instance_name}"
            label += f" · {self._time(ctx, run.requested_at)}{size}{remote}"
            keyboard.append([button(label, f"r:{run.id}")])
        pager = self._pager(ctx, f"rl:{instance_id}", page, total, PAGE_SIZE)
        if pager:
            keyboard.append(pager)
        keyboard.append(
            [
                button(t(lang, "btn_refresh"), f"rl:{instance_id}:{page}"),
                button(t(lang, "btn_back"), back_target),
            ]
        )
        return Screen(t(lang, "runs_title", scope=scope, page=page + 1), keyboard)

    def _run_text(self, ctx: Ctx, run: BackupRun) -> str:
        lang = ctx.lang
        lines = [
            t(
                lang,
                "run_title",
                icon=STATUS_ICONS.get(run.status, ""),
                db=run.database_name,
                instance=run.instance_name,
            ),
            t(lang, "run_status", status=t(lang, f"status_{run.status}")),
            t(lang, "run_trigger", trigger=t(lang, f"trigger_{run.trigger}")),
            t(lang, "run_requested", time=self._time(ctx, run.requested_at)),
        ]
        if run.duration_ms is not None:
            lines.append(t(lang, "run_duration", duration=format_duration(run.duration_ms, lang)))
        if run.file_size is not None:
            lines.append(
                t(
                    lang,
                    "run_size",
                    size=format_size(run.file_size, lang),
                    compression=run.compression or "",
                )
            )
        if run.checksum_sha256:
            lines.append(t(lang, "run_checksum", checksum=run.checksum_sha256[:16] + "…"))
        if run.status == "success":
            remote = (
                t(lang, f"remote_{run.remote_status}")
                if run.remote_status
                else t(lang, "remote_none")
            )
            if run.remote_status == "failed" and run.remote_error:
                remote += f" ({run.remote_error[:200]})"
            lines.append(t(lang, "run_remote", remote=remote))
        if run.file_deleted_at:
            lines.append(t(lang, "run_retention", time=self._time(ctx, run.file_deleted_at)))
        if run.status == "failed":
            error = run.error_code or ""
            if run.error_message:
                error = f"{error} — {run.error_message[:400]}"
            lines.append(t(lang, "run_error", error=error))
        return "\n".join(lines)

    def run(self, db: Session, ctx: Ctx, run_id: int) -> Screen:
        lang = ctx.lang
        run = BackupService(db, None, self.store).get(run_id)
        keyboard: Keyboard = []
        if run.status == "success":
            row = []
            if run.has_local_file and self.store.exists(run.file_path):
                row.append(button(t(lang, "btn_download"), f"rf:{run.id}"))
            remote = RemoteStorageRepository(db).get()
            if (
                is_configured(remote)
                and run.has_local_file
                and run.remote_status in (None, "failed", "deleted")
            ):
                row.append(button(t(lang, "btn_upload"), f"ru:{run.id}"))
            if row:
                keyboard.append(row)
        actions = [button(t(lang, "btn_refresh"), f"r:{run.id}")]
        # Something the panel may delete: a local file, an unprotected remote copy, or a
        # record without any file (a failed run).
        deletable = (
            run.has_local_file or not run.has_remote_copy or run.remote_deletable(self.clock())
        )
        if deletable and not run.is_active and run.remote_status != "uploading":
            actions.append(button(t(lang, "btn_delete"), f"rd:{run.id}"))
        keyboard.append(actions)
        keyboard.append(
            [
                button(t(lang, "btn_back"), f"rl:{run.instance_id or 0}:0"),
                button(t(lang, "btn_menu"), "m"),
            ]
        )
        return Screen(self._run_text(ctx, run), keyboard)

    def send_file(self, db: Session, ctx: Ctx, run_id: int, chat_id: int) -> Screen | None:
        lang = ctx.lang
        run = BackupService(db, None, self.store).get(run_id)
        settings = BotRepository(db).get_settings(self.platform)
        notice = None
        if not settings.allow_file_download:
            notice = t(lang, "file_disabled")
        elif not run.has_local_file or not self.store.exists(run.file_path):
            notice = t(lang, "file_unavailable")
        elif (run.file_size or 0) > settings.max_file_mb * 1024 * 1024:
            notice = t(
                lang,
                "file_too_large",
                size=format_size(run.file_size, lang),
                limit=format_size(settings.max_file_mb * 1024 * 1024, lang),
            )
        if notice is not None:
            screen = self.run(db, ctx, run_id)
            return Screen(f"{notice}\n\n{screen.text}", screen.keyboard)
        path = self.store.path_for_download(run.file_path or "")
        logger.info("%s bot: admin %s downloaded run %s", self.platform, ctx.admin_id, run_id)
        self.api.send_document(
            chat_id,
            path,
            PurePosixPath(run.file_path or "").name,
            t(
                lang,
                "file_caption",
                db=run.database_name,
                instance=run.instance_name,
                time=self._time(ctx, run.requested_at),
                checksum=run.checksum_sha256 or "",
            ),
        )
        return None

    def upload(self, db: Session, ctx: Ctx, run_id: int) -> Screen:
        BackupService(db, self.runner, self.store).retry_upload(run_id)
        screen = self.run(db, ctx, run_id)
        return Screen(f"{t(ctx.lang, 'upload_queued')}\n\n{screen.text}", screen.keyboard)

    def confirm_delete(self, db: Session, ctx: Ctx, run_id: int) -> Screen:
        lang = ctx.lang
        run = BackupService(db, None, self.store).get(run_id)
        lines = [
            t(lang, "confirm_delete", db=run.database_name, time=self._time(ctx, run.requested_at))
        ]
        rows: Keyboard = []
        if run.has_local_file:
            rows.append([button(t(lang, "btn_delete_local"), f"rdc:{run_id}:0")])
        if run.has_remote_copy:
            if run.remote_deletable(self.clock()):
                label = "btn_delete_both" if run.has_local_file else "btn_delete_remote"
                rows.append([button(t(lang, label), f"rdc:{run_id}:1")])
            else:
                lines.append(
                    t(lang, "remote_protected", time=self._time(ctx, run.remote_deletable_at))
                )
        rows.append([button(t(lang, "btn_cancel"), f"r:{run_id}")])
        return Screen("\n\n".join(lines), rows)

    def delete(self, db: Session, ctx: Ctx, run_id: int, *, remote: bool = False) -> Screen:
        run = BackupService(db, None, self.store).get(run_id)
        instance_id = run.instance_id or 0
        kept = run.has_remote_copy and not remote
        BackupService(db, None, self.store).delete(run_id, delete_remote=remote)
        logger.info(
            "%s bot: admin %s deleted run %s (remote: %s)",
            self.platform,
            ctx.admin_id,
            run_id,
            remote,
        )
        return Screen(
            t(ctx.lang, "deleted_local_kept_remote" if kept else "deleted"),
            [
                [
                    button(t(ctx.lang, "btn_back"), f"rl:{instance_id}:0"),
                    button(t(ctx.lang, "btn_menu"), "m"),
                ]
            ],
        )

    def schedules(self, db: Session, ctx: Ctx, instance_id: int) -> Screen:
        lang = ctx.lang
        items = ScheduleService(db).list_all(instance_id or None)
        scope = ""
        if instance_id:
            scope = t(lang, "runs_scope", name=InstanceService(db).get(instance_id).name)
        back = [
            button(t(lang, "btn_back"), f"i:{instance_id}" if instance_id else "m"),
            button(t(lang, "btn_menu"), "m"),
        ]
        if not items:
            return Screen(t(lang, "schedules_empty"), [back])
        names = {i.id: i.name for i in InstanceService(db).list()}
        keyboard: Keyboard = []
        for schedule in items[:40]:
            icon = "🟢" if schedule.enabled else "⏸"
            label = f"{icon} {schedule.name}"
            if not instance_id:
                label += f" · {names.get(schedule.instance_id, '')}"
            keyboard.append([button(label, f"s:{schedule.id}")])
        keyboard.append(back)
        return Screen(t(lang, "schedules_title", scope=scope), keyboard)

    def schedule(self, db: Session, ctx: Ctx, schedule_id: int) -> Screen:
        lang = ctx.lang
        schedule = ScheduleService(db).get(schedule_id)
        instance = InstanceService(db).get(schedule.instance_id)
        lines = [
            t(lang, "schedule_title", name=schedule.name, instance=instance.name),
            t(lang, "schedule_when", cron=schedule.cron, tz=schedule.timezone),
            (
                t(lang, "schedule_scope_all")
                if schedule.scope == "all"
                else t(lang, "schedule_scope_single", db=schedule.database_name)
            ),
            t(lang, "schedule_state_on") if schedule.enabled else t(lang, "schedule_state_off"),
        ]
        if schedule.enabled:
            lines.append(t(lang, "schedule_next", time=self._time(ctx, next_run_at(schedule))))
        if schedule.last_fired_at:
            lines.append(
                t(
                    lang,
                    "schedule_last",
                    result=self._error(ctx, schedule.last_result or "error"),
                    time=self._time(ctx, schedule.last_fired_at),
                )
            )
        return Screen(
            "\n".join(lines),
            [
                [
                    button(
                        t(lang, "btn_disable") if schedule.enabled else t(lang, "btn_enable"),
                        f"se:{schedule_id}",
                    ),
                    button(t(lang, "btn_run_now"), f"sr:{schedule_id}"),
                ],
                [
                    button(t(lang, "btn_back"), f"sl:{schedule.instance_id}"),
                    button(t(lang, "btn_menu"), "m"),
                ],
            ],
        )

    def toggle_schedule(self, db: Session, ctx: Ctx, schedule_id: int) -> Screen:
        service = ScheduleService(db)
        schedule = service.get(schedule_id)
        service.update(
            schedule_id,
            ScheduleIn(
                name=schedule.name,
                cron=schedule.cron,
                timezone=schedule.timezone,
                scope=schedule.scope,  # type: ignore[arg-type]
                database=schedule.database_name,
                enabled=not schedule.enabled,
            ),
        )
        if self.scheduler is not None and self.scheduler.running:
            self.scheduler.sync(schedule_id)
        logger.info(
            "%s bot: admin %s toggled schedule %s", self.platform, ctx.admin_id, schedule_id
        )
        return self.schedule(db, ctx, schedule_id)

    def run_schedule(self, db: Session, ctx: Ctx, schedule_id: int) -> Screen:
        ScheduleService(db).get(schedule_id)
        db.commit()
        if self.scheduler is not None:
            result = self.scheduler.fire(schedule_id, force=True)
        else:
            from mbp.backups.scheduler import fire_schedule

            result = fire_schedule(
                schedule_id, self.session_factory, self.runner, self.store, force=True
            )
        logger.info("%s bot: admin %s ran schedule %s", self.platform, ctx.admin_id, schedule_id)
        db.expire_all()
        screen = self.schedule(db, ctx, schedule_id)
        text = t(ctx.lang, "schedule_fired", result=self._error(ctx, result or "error"))
        return Screen(f"{text}\n\n{screen.text}", screen.keyboard)

    def _policy(self, ctx: Ctx, keep: int | None, age: int | None) -> str:
        parts = []
        if keep is not None:
            parts.append(t(ctx.lang, "retention_keep", n=keep))
        if age is not None:
            parts.append(t(ctx.lang, "retention_age", n=age))
        if not parts:
            return t(ctx.lang, "retention_all")
        return ("، " if ctx.lang == "fa" else ", ").join(parts)

    def retention(self, db: Session, ctx: Ctx) -> Screen:
        policy = global_retention(db)
        lines = [
            t(ctx.lang, "retention_title"),
            t(
                ctx.lang,
                "retention_local",
                policy=self._policy(ctx, policy.local.keep_last, policy.local.max_age_days),
            ),
            t(
                ctx.lang,
                "retention_remote",
                policy=self._policy(ctx, policy.remote.keep_last, policy.remote.max_age_days),
            ),
            "",
            t(ctx.lang, "retention_note"),
        ]
        return Screen(
            "\n".join(lines),
            [[button(t(ctx.lang, "btn_preview"), "rtp")], [button(t(ctx.lang, "btn_menu"), "m")]],
        )

    def retention_preview(self, db: Session, ctx: Ctx) -> Screen:
        report = RetentionService(db, self.store).apply(dry_run=True)
        if not report.deleted:
            return Screen(
                t(ctx.lang, "retention_nothing"),
                [[button(t(ctx.lang, "btn_back"), "rt"), button(t(ctx.lang, "btn_menu"), "m")]],
            )
        items = [
            f"{'☁️' if item.target == 'remote' else '💾'} "
            f"{item.instance_name}/{item.file_name or item.database_name}"
            for item in report.deleted[:PREVIEW_LIMIT]
        ]
        if len(report.deleted) > PREVIEW_LIMIT:
            items.append("…")
        return Screen(
            t(ctx.lang, "retention_preview", n=len(report.deleted), items="\n".join(items)),
            [
                [button(t(ctx.lang, "btn_apply", n=len(report.deleted)), "rta")],
                [button(t(ctx.lang, "btn_cancel"), "rt")],
            ],
        )

    def retention_apply(self, db: Session, ctx: Ctx) -> Screen:
        report = RetentionService(db, self.store).apply(dry_run=False)
        logger.info("%s bot: admin %s applied retention", self.platform, ctx.admin_id)
        return Screen(
            t(
                ctx.lang,
                "retention_applied",
                deleted=len(report.deleted),
                errors=len(report.errors),
            ),
            [[button(t(ctx.lang, "btn_back"), "rt"), button(t(ctx.lang, "btn_menu"), "m")]],
        )

    def settings(self, db: Session, ctx: Ctx) -> Screen:
        admin = BotService(db).get_admin(ctx.admin_id)
        lang = ctx.lang
        keyboard: Keyboard = [
            [
                button(
                    ("● " if admin.notify_level == level else "") + t(lang, f"level_{level}"),
                    f"nl:{level}",
                )
            ]
            for level in LEVELS
        ]
        keyboard.append([button(t(lang, "btn_language"), "lg"), button(t(lang, "btn_menu"), "m")])
        text = "\n".join(
            [
                t(lang, "settings_title"),
                t(lang, "settings_level", level=t(lang, f"level_{admin.notify_level}")),
                "",
                t(lang, "settings_hint"),
            ]
        )
        return Screen(text, keyboard)

    def set_level(self, db: Session, ctx: Ctx, level: str) -> Screen:
        if level in LEVELS:
            BotService(db).update_admin(ctx.admin_id, notify_level=level)
        return self.settings(db, ctx)

    def toggle_language(self, db: Session, ctx: Ctx) -> Screen:
        language = "en" if ctx.lang == "fa" else "fa"
        BotService(db).update_admin(ctx.admin_id, language=language)
        ctx.lang = language
        return self.settings(db, ctx)
