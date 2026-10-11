from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbp.models import ContainerAction, ContainerSettings

SETTINGS_ID = 1


class ContainerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self) -> ContainerSettings:
        """The settings row, or unsaved defaults if it is missing (reads never insert)."""
        row = self.db.get(ContainerSettings, SETTINGS_ID)
        if row is None:
            return ContainerSettings(
                id=SETTINGS_ID,
                read_only=False,
                hidden=[],
                locked=[],
                monitor_all=True,
                monitored=[],
                cpu_percent=90,
                memory_percent=90,
                restart_count=3,
                restart_window_minutes=10,
                host_memory_percent=90,
                host_disk_percent=90,
                bot_logs=False,
            )
        return row

    def get_settings_for_update(self) -> ContainerSettings:
        row = self.db.get(ContainerSettings, SETTINGS_ID)
        if row is None:
            row = self.get_settings()
            self.db.add(row)
        return row

    def add_action(self, entry: ContainerAction) -> None:
        self.db.add(entry)

    def actions_page(
        self, page: int, page_size: int, container: str | None = None
    ) -> tuple[list[ContainerAction], int]:
        stmt = select(ContainerAction)
        count = select(func.count()).select_from(ContainerAction)
        if container:
            stmt = stmt.where(ContainerAction.container == container)
            count = count.where(ContainerAction.container == container)
        stmt = (
            stmt.order_by(ContainerAction.created_at.desc(), ContainerAction.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), self.db.scalar(count) or 0
