from collections.abc import Collection
from datetime import datetime

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from mbp.models import WebAction, WebCheck, WebCheckResult, WebServerSettings

# Results kept per check: a day at the default interval of 5 minutes.
KEEP_RESULTS = 288


class WebServerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self, server_id: int) -> WebServerSettings:
        """A server's settings (row id = server id), or unsaved defaults (reads never insert)."""
        row = self.db.get(WebServerSettings, server_id)
        if row is None:
            return WebServerSettings(
                id=server_id,
                read_only=False,
                cert_warning_days=14,
                check_interval_minutes=5,
                check_timeout_seconds=10,
                check_failures=2,
                acme_email=None,
            )
        return row

    def get_settings_for_update(self, server_id: int) -> WebServerSettings:
        row = self.db.get(WebServerSettings, server_id)
        if row is None:
            row = self.get_settings(server_id)
            self.db.add(row)
        return row

    # --- audit log ---

    def add_action(self, entry: WebAction) -> WebAction:
        self.db.add(entry)
        return entry

    def action_by_job(self, server_id: int, job_id: str) -> WebAction | None:
        return self.db.scalar(
            select(WebAction).where(WebAction.server_id == server_id, WebAction.job_id == job_id)
        )

    def actions_page(
        self,
        page: int,
        page_size: int,
        server_id: int | None = None,
        server_ids: Collection[int] | None = None,
    ) -> tuple[list[WebAction], int]:
        """`server_ids`: only the actions on these servers."""
        stmt = select(WebAction)
        count = select(func.count()).select_from(WebAction)
        if server_ids is not None:
            stmt = stmt.where(WebAction.server_id.in_(sorted(server_ids)))
            count = count.where(WebAction.server_id.in_(sorted(server_ids)))
        if server_id is not None:
            stmt = stmt.where(WebAction.server_id == server_id)
            count = count.where(WebAction.server_id == server_id)
        stmt = (
            stmt.order_by(WebAction.created_at.desc(), WebAction.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(self.db.scalar(count) or 0)

    def last_action(self, server_id: int, kind: str, actions: tuple[str, ...]) -> WebAction | None:
        return self.db.scalar(
            select(WebAction)
            .where(
                WebAction.server_id == server_id,
                WebAction.kind == kind,
                WebAction.action.in_(actions),
                WebAction.result == "ok",
            )
            .order_by(WebAction.created_at.desc(), WebAction.id.desc())
            .limit(1)
        )

    # --- health checks ---

    def checks(self, server_id: int | None = None) -> list[WebCheck]:
        stmt = select(WebCheck).order_by(WebCheck.url)
        if server_id is not None:
            stmt = stmt.where(WebCheck.server_id == server_id)
        return list(self.db.scalars(stmt))

    def check(self, check_id: int) -> WebCheck | None:
        return self.db.get(WebCheck, check_id)

    def check_by_url(self, server_id: int, url: str) -> WebCheck | None:
        return self.db.scalar(
            select(WebCheck).where(WebCheck.server_id == server_id, WebCheck.url == url)
        )

    def recent_results(self, check_ids: list[int], limit: int) -> dict[int, list[WebCheckResult]]:
        out: dict[int, list[WebCheckResult]] = {i: [] for i in check_ids}
        for check_id in check_ids:
            rows = self.db.scalars(
                select(WebCheckResult)
                .where(WebCheckResult.check_id == check_id)
                .order_by(WebCheckResult.checked_at.desc(), WebCheckResult.id.desc())
                .limit(limit)
            )
            out[check_id] = list(rows)
        return out

    def add_result(self, result: WebCheckResult) -> None:
        self.db.add(result)
        self.db.flush()
        keep = select(WebCheckResult.id).where(WebCheckResult.check_id == result.check_id)
        keep = keep.order_by(WebCheckResult.id.desc()).limit(KEEP_RESULTS)
        ids = list(self.db.scalars(keep))
        if len(ids) >= KEEP_RESULTS:
            self.db.execute(
                delete(WebCheckResult).where(
                    WebCheckResult.check_id == result.check_id, WebCheckResult.id < min(ids)
                )
            )

    def uptime(self, check_id: int, since: datetime) -> float | None:
        """The share of successful checks since a time, in percent."""
        total, ok = self.db.execute(
            select(
                func.count(WebCheckResult.id),
                func.sum(case((WebCheckResult.ok.is_(True), 1), else_=0)),
            ).where(WebCheckResult.check_id == check_id, WebCheckResult.checked_at >= since)
        ).one()
        if not total:
            return None
        return round(float(ok or 0) * 100 / total, 2)
