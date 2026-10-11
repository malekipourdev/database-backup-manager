from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from mbp.models import AlertState, NotificationLog, NotificationSettings

SETTINGS_ID = 1


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self) -> NotificationSettings:
        """The settings row, or unsaved defaults if it is missing (reads never insert)."""
        row = self.db.get(NotificationSettings, SETTINGS_ID)
        if row is None:
            return NotificationSettings(
                id=SETTINGS_ID,
                rules={},
                cooldown_minutes=60,
                stale_hours=26,
                disk_free_percent=10,
                daily_summary_time="08:00",
                timezone="Asia/Tehran",
                webhook_enabled=False,
                webhook_url="",
                webhook_secret_encrypted=None,
            )
        return row

    def get_settings_for_update(self) -> NotificationSettings:
        row = self.db.get(NotificationSettings, SETTINGS_ID)
        if row is None:
            row = self.get_settings()
            self.db.add(row)
        return row

    def log_page(
        self, page: int, page_size: int, severity: str | None = None, event: str | None = None
    ) -> tuple[list[NotificationLog], int]:
        stmt = select(NotificationLog)
        count = select(func.count()).select_from(NotificationLog)
        if severity:
            stmt = stmt.where(NotificationLog.severity == severity)
            count = count.where(NotificationLog.severity == severity)
        if event:
            stmt = stmt.where(NotificationLog.event == event)
            count = count.where(NotificationLog.event == event)
        stmt = (
            stmt.order_by(NotificationLog.created_at.desc(), NotificationLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), self.db.scalar(count) or 0

    def purge_log_before(self, cutoff: datetime) -> None:
        self.db.execute(delete(NotificationLog).where(NotificationLog.created_at < cutoff))

    # --- condition alerts ---

    def active_states(self, prefix: str) -> dict[str, AlertState]:
        stmt = select(AlertState).where(AlertState.key.startswith(prefix))
        return {state.key: state for state in self.db.scalars(stmt)}

    def activate(self, key: str, since: datetime) -> None:
        self.db.add(AlertState(key=key, active_since=since))

    def deactivate(self, state: AlertState) -> None:
        self.db.delete(state)
