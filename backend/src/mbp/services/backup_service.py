from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.backups.runner import BackupRunner
from mbp.backups.store import LocalBackupStore
from mbp.models import BackupRun
from mbp.repositories.backup_run_repository import BackupRunRepository, RunFilters
from mbp.repositories.selection_repository import SelectionRepository
from mbp.services.instance_service import InstanceService
from mbp.services.selection_service import NON_SELECTABLE


class BackupService:
    def __init__(self, db: Session, runner: BackupRunner | None, store: LocalBackupStore) -> None:
        self.db = db
        self.runner = runner
        self.store = store
        self.runs = BackupRunRepository(db)

    def start(
        self, instance_id: int, scope: str, database: str | None
    ) -> tuple[list[BackupRun], list[dict]]:
        """Create queued runs and hand them to the runner; returns (created, skipped)."""
        instance = InstanceService(self.db).get(instance_id)
        if scope == "all":
            names = SelectionRepository(self.db).list_names(instance_id)
            if not names:
                raise ApiError(422, "no_databases_selected")
            trigger = "all"
        else:
            if database in NON_SELECTABLE:
                raise ApiError(
                    422, "not_selectable", detail=database, fields={"database": "not_selectable"}
                )
            names = [database]
            trigger = "single"

        created: list[BackupRun] = []
        skipped: list[dict] = []
        for name in names:
            run = self.runs.create_queued(instance, name, trigger)
            if run is None:
                skipped.append({"database": name, "reason": "already_in_progress"})
            else:
                created.append(run)
        if self.runner is not None:
            for run in created:
                self.runner.enqueue(run.id)
        return created, skipped

    def get(self, run_id: int) -> BackupRun:
        run = self.runs.get(run_id)
        if run is None:
            raise ApiError(404, "run_not_found")
        return run

    def list(
        self, filters: RunFilters, sort: str, order: str, page: int, page_size: int
    ) -> tuple[list[BackupRun], int]:
        return self.runs.query(filters, sort, order, page, page_size)

    def delete(self, run_id: int) -> None:
        run = self.get(run_id)
        if run.is_active:
            raise ApiError(409, "run_active")
        self.store.delete(run.file_path)
        self.runs.delete(run)
        self.db.commit()
