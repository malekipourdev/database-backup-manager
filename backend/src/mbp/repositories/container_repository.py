from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbp.models import ContainerAction, ContainerSettings


class ContainerRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self, server_id: int) -> ContainerSettings:
        """A server's settings (row id = server id), or unsaved defaults (reads never insert)."""
        row = self.db.get(ContainerSettings, server_id)
        if row is None:
            return ContainerSettings(
                id=server_id,
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

    def get_settings_for_update(self, server_id: int) -> ContainerSettings:
        row = self.db.get(ContainerSettings, server_id)
        if row is None:
            row = self.get_settings(server_id)
            self.db.add(row)
        return row

    def add_action(self, entry: ContainerAction) -> None:
        self.db.add(entry)

    def actions_page(
        self,
        page: int,
        page_size: int,
        container: str | None = None,
        server_id: int | None = None,
    ) -> tuple[list[ContainerAction], int]:
        stmt = select(ContainerAction)
        count = select(func.count()).select_from(ContainerAction)
        if server_id is not None:
            stmt = stmt.where(ContainerAction.server_id == server_id)
            count = count.where(ContainerAction.server_id == server_id)
        if container:
            stmt = stmt.where(ContainerAction.container == container)
            count = count.where(ContainerAction.container == container)
        stmt = (
            stmt.order_by(ContainerAction.created_at.desc(), ContainerAction.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), self.db.scalar(count) or 0
