from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.backups.dump_command import is_safe_database_name
from mbp.backups.remote import RemoteError
from mbp.backups.runner import BackupRunner
from mbp.backups.store import LocalBackupStore
from mbp.db import utcnow
from mbp.models import BackupRun
from mbp.repositories.backup_run_repository import BackupRunRepository, RunFilters
from mbp.repositories.selection_repository import SelectionRepository
from mbp.services.instance_service import InstanceService
from mbp.services.remote_storage_service import get_remote_storage
from mbp.services.selection_service import NON_SELECTABLE


class BackupService:
    def __init__(self, db: Session, runner: BackupRunner | None, store: LocalBackupStore) -> None:
        self.db = db
        self.runner = runner
        self.store = store
        self.runs = BackupRunRepository(db)

    def start(
        self,
        instance_id: int,
        scope: str,
        database: str | None,
        *,
        trigger: str | None = None,
        schedule_id: int | None = None,
    ) -> tuple[list[BackupRun], list[dict]]:
        """Create queued runs and hand them to the runner; returns (created, skipped)."""
        instance = InstanceService(self.db).get(instance_id)
        if scope == "all":
            names = SelectionRepository(self.db).list_names(instance_id)
            if not names:
                raise ApiError(422, "no_databases_selected")
            trigger = trigger or "all"
        else:
            if database is None or not is_safe_database_name(database):
                raise ApiError(
                    422,
                    "invalid_database_name",
                    fields={"database": "invalid_database_name"},
                )
            if database in NON_SELECTABLE:
                raise ApiError(
                    422, "not_selectable", detail=database, fields={"database": "not_selectable"}
                )
            names = [database]
            trigger = trigger or "single"

        created: list[BackupRun] = []
        skipped: list[dict] = []
        for name in names:
            run = self.runs.create_queued(instance, name, trigger, schedule_id)
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

    def delete(self, run_id: int, *, delete_remote: bool = False) -> None:
        """Delete a finished run's local file; its remote copy only when asked and allowed.

        While a remote copy is kept, the run stays in the history (marked as deleted
        locally) so the copy can still be found and downloaded. The record goes away
        once neither a local file nor a remote copy is left.
        """
        run = self.get(run_id)
        if run.is_active:
            raise ApiError(409, "run_active")
        if run.remote_status == "uploading":
            raise ApiError(409, "upload_in_progress")
        now = utcnow()
        has_local = run.has_local_file
        remote_kept = run.has_remote_copy and not delete_remote
        if delete_remote and run.has_remote_copy:
            if not run.remote_deletable(now):
                deletable_at = run.remote_deletable_at
                raise ApiError(
                    409,
                    "remote_protected",
                    detail=deletable_at.isoformat() if deletable_at else None,
                )
            _, storage = get_remote_storage(self.db)
            if storage is None:
                raise ApiError(409, "remote_not_configured")
            try:
                storage.delete(run.remote_key or "")
            except RemoteError as exc:
                raise ApiError(502, "remote_delete_failed", detail=exc.code) from exc
        if remote_kept and not has_local:
            # Only a protected (or not to be deleted) remote copy is left: nothing to do.
            raise ApiError(409, "nothing_to_delete")
        if has_local:
            self.store.delete(run.file_path)
        if remote_kept:
            run.file_deleted_at = now
            run.file_deleted_reason = "manual"
        else:
            self.runs.delete(run)
        self.db.commit()

    def retry_upload(self, run_id: int) -> BackupRun:
        """Queue an upload of a successful run that is not (or no longer) stored remotely."""
        run = self.get(run_id)
        if not run.has_local_file or not self.store.exists(run.file_path):
            raise ApiError(409, "file_unavailable")
        if run.remote_status in ("uploading", "success"):
            raise ApiError(409, "already_uploaded")
        _, storage = get_remote_storage(self.db)
        if storage is None:
            raise ApiError(409, "remote_not_configured")
        if self.runner is None:
            raise RuntimeError("backup runner is required to upload")
        # Claim it now: a second click finds it uploading, and history shows it at once.
        run.remote_status = "uploading"
        run.remote_error = None
        self.db.commit()
        self.runner.enqueue_upload(run.id)
        return run
