"""In-process backup execution: a bounded thread pool running one dump per worker."""

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from mbp.backups import dump_command, errors, naming
from mbp.backups.dump_command import ToolMissing
from mbp.backups.pipeline import DumpProcess
from mbp.backups.remote import RemoteError, join_key
from mbp.backups.store import LocalBackupStore, StorageError
from mbp.backups.verify import verify
from mbp.config import Settings
from mbp.db import utcnow
from mbp.models import DbInstance
from mbp.repositories.backup_run_repository import BackupRunRepository
from mbp.repositories.remote_storage_repository import RemoteStorageRepository
from mbp.services import mysql_probe
from mbp.services.backup_settings_service import effective_for
from mbp.services.instance_service import conn_params
from mbp.services.remote_storage_service import get_remote_storage, upload_enabled_for
from mbp.services.retention_service import RetentionService

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Interrupted by panel restart or shutdown."
UPLOAD_INTERRUPTED_MESSAGE = "Upload interrupted by panel restart or shutdown."


class _Failure(Exception):
    def __init__(self, code: str, message: str | None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class BackupRunner:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        store: LocalBackupStore,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.store = store
        self._executor: ThreadPoolExecutor | None = None
        self._processes: dict[int, DumpProcess] = {}
        self._lock = threading.Lock()
        self._stopping = False
        # Test hook: called with the temp file path between writing and verification.
        self.before_verify: Callable[[Path], None] | None = None

    # --- lifecycle ---

    def recover(self) -> int:
        """Fail runs left queued/running by a previous process and remove temp files."""
        with self.session_factory() as db:
            repo = BackupRunRepository(db)
            stale = repo.list_active()
            for run in stale:
                repo.finish_failed(run, "interrupted", INTERRUPTED_MESSAGE)
            for run in repo.list_interrupted_uploads():
                run.remote_status = "failed"
                run.remote_error = UPLOAD_INTERRUPTED_MESSAGE
            db.commit()
        removed = self.store.cleanup_partials()
        if stale or removed:
            logger.warning(
                "Recovered %d interrupted backup run(s), removed %d temp file(s)",
                len(stale),
                removed,
            )
        return len(stale)

    def start(self) -> None:
        self._stopping = False
        self._executor = ThreadPoolExecutor(
            max_workers=self.settings.backup_concurrency, thread_name_prefix="mbp-backup"
        )

    def stop(self) -> None:
        """Terminate running dumps, drop queued work, and record them as interrupted."""
        self._stopping = True
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            process.terminate()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        self.recover()

    def enqueue(self, run_id: int) -> None:
        if self._executor is None:
            raise RuntimeError("backup runner is not started")
        self._executor.submit(self._execute_safely, run_id)

    def enqueue_upload(self, run_id: int) -> None:
        """Queue the upload of a run already claimed with remote_status "uploading"."""
        if self._executor is None:
            raise RuntimeError("backup runner is not started")
        self._executor.submit(self._upload_safely, run_id)

    def active_pids(self) -> dict[int, int]:
        """run_id -> pid of running dump processes (used by tests and diagnostics)."""
        with self._lock:
            return {
                run_id: process.process.pid
                for run_id, process in self._processes.items()
                if process.process is not None
            }

    # --- execution ---

    def _execute_safely(self, run_id: int) -> None:
        try:
            self._execute(run_id)
        except Exception:
            # Last resort: a run must never stay "running" after its worker exits.
            logger.exception("Unexpected error in backup run %s", run_id)
            self._record_failure(run_id, "dump_failed", "Unexpected internal error.")

    def _record_failure(self, run_id: int, code: str, message: str | None) -> None:
        with self.session_factory() as db:
            repo = BackupRunRepository(db)
            run = repo.get(run_id)
            if run is not None and run.is_active:
                repo.finish_failed(run, code, message)
                db.commit()

    def _report_progress(self, run_id: int, processed: int) -> None:
        try:
            with self.session_factory() as db:
                BackupRunRepository(db).update_progress(run_id, processed)
                db.commit()
        except Exception:
            # Progress is informational; never fail a backup because of it.
            logger.debug("Could not record progress for run %s", run_id, exc_info=True)

    def _execute(self, run_id: int) -> None:
        with self.session_factory() as db:
            repo = BackupRunRepository(db)
            run = repo.get(run_id)
            if run is None or run.status != "queued":
                return
            if self._stopping:
                repo.finish_failed(run, "interrupted", INTERRUPTED_MESSAGE)
                db.commit()
                return
            instance = db.get(DbInstance, run.instance_id) if run.instance_id else None
            if instance is None:
                repo.finish_failed(run, "instance_deleted", "The instance was deleted.")
                db.commit()
                return
            params = conn_params(instance)
            effective = effective_for(db, instance)
            instance_name = run.instance_name
            database = run.database_name
            repo.mark_running(run, effective.compression)
            db.commit()

        temp: Path | None = None
        try:
            if not dump_command.is_safe_database_name(database):
                raise _Failure("invalid_database_name", "The database name is not allowed.")
            probe = mysql_probe.test_connection(params)
            if not probe.ok:
                raise _Failure(probe.error_code or "server_error", probe.error_detail)
            with self.session_factory() as db:
                repo = BackupRunRepository(db)
                run = repo.get(run_id)
                repo.set_server(run, probe.server_type, probe.server_version)
                db.commit()

            tool = dump_command.tool_for(probe.server_type, self.settings)
            rendered = naming.render(
                effective.name_pattern,
                instance=instance_name,
                database=database,
                server_type=probe.server_type,
                now=utcnow(),
                compression=effective.compression,
            )
            relative, temp = self.store.prepare(effective.storage_dir, rendered, run_id)

            with dump_command.option_file(params.username, params.password) as cnf:
                args = dump_command.build_args(
                    tool,
                    cnf,
                    host=params.host,
                    port=params.port,
                    server_type=probe.server_type,
                    server_version=probe.server_version,
                    database=database,
                )
                process = DumpProcess(args, home=cnf.parent)
                with self._lock:
                    self._processes[run_id] = process
                try:
                    if self._stopping:
                        process.terminate()
                    result = process.run(
                        temp,
                        effective.compression,
                        lambda n: self._report_progress(run_id, n),
                        self.settings.backup_progress_interval_seconds,
                    )
                finally:
                    with self._lock:
                        self._processes.pop(run_id, None)

            if process.terminated or self._stopping:
                raise _Failure("interrupted", INTERRUPTED_MESSAGE)
            if result.returncode != 0:
                raise _Failure(
                    *errors.classify_dump_failure(
                        result.returncode, result.stderr_tail, params.password
                    )
                )
            if self.before_verify is not None:
                self.before_verify(temp)
            check = verify(temp, effective.compression, result.sha256)
            if not check.ok:
                raise _Failure("verification_failed", errors.VERIFY_MESSAGES[check.reason])

            final_relative = self.store.publish(temp, relative)
            temp = None
            with self.session_factory() as db:
                repo = BackupRunRepository(db)
                run = repo.get(run_id)
                repo.finish_success(
                    run,
                    file_path=final_relative,
                    file_size=result.size,
                    checksum=result.sha256,
                    bytes_processed=result.bytes_processed,
                )
                instance = db.get(DbInstance, run.instance_id) if run.instance_id else None
                # Claimed in the same commit, so the run never looks finished-but-not-uploaded.
                will_upload = upload_enabled_for(RemoteStorageRepository(db).get(), instance)
                if will_upload:
                    run.remote_status = "uploading"
                db.commit()
            logger.info("Backup run %s succeeded (%s bytes)", run_id, result.size)
            self._after_success(run_id, will_upload)
        except _Failure as failure:
            self.store.discard(temp)
            self._record_failure(run_id, failure.code, failure.message)
        except ToolMissing as exc:
            self.store.discard(temp)
            self._record_failure(run_id, "tool_missing", f"Dump tool not found: {exc}")
        except StorageError as exc:
            self.store.discard(temp)
            self._record_failure(run_id, "storage_error", str(exc))
        except OSError as exc:
            self.store.discard(temp)
            self._record_failure(run_id, *errors.classify_os_error(exc))
        finally:
            # Covers unexpected exceptions too (handled by _execute_safely).
            self.store.discard(temp)

    # --- after a successful backup: remote upload, then retention ---

    def _after_success(self, run_id: int, upload: bool) -> None:
        # The backup itself already succeeded; failures here are recorded on the run
        # (remote_status/remote_error) or logged, never turned into a failed backup.
        if upload:
            self._upload_safely(run_id)
        try:
            self.apply_retention_for(run_id)
        except Exception:
            logger.exception("Unexpected error applying retention after run %s", run_id)

    def _upload_safely(self, run_id: int) -> None:
        try:
            self.upload(run_id)
        except Exception:
            logger.exception("Unexpected error uploading backup run %s", run_id)
            self._record_upload_failure(run_id, "Unexpected internal error.")

    def _record_upload_failure(self, run_id: int, message: str) -> None:
        with self.session_factory() as db:
            run = BackupRunRepository(db).get(run_id)
            if run is not None and run.remote_status == "uploading":
                run.remote_status = "failed"
                run.remote_error = message[:1000]
                db.commit()

    def upload(self, run_id: int) -> bool:
        """Upload a run claimed for upload (remote_status "uploading"); True if stored."""
        with self.session_factory() as db:
            run = BackupRunRepository(db).get(run_id)
            if run is None or run.remote_status != "uploading":
                return False
            if not run.has_local_file:
                run.remote_status = "failed"
                run.remote_error = "The local backup file no longer exists."
                db.commit()
                return False
            row, storage = get_remote_storage(db)
            if storage is None:
                run.remote_status = "failed"
                run.remote_error = "Remote storage is not configured."
                db.commit()
                return False
            key = join_key(row.prefix, run.file_path or "")
            relative = run.file_path or ""
            checksum = run.checksum_sha256 or ""
            run.remote_key = key
            run.remote_error = None
            db.commit()

        try:
            local = self.store.path_for_download(relative)
            storage.upload(local, key, checksum)
        except RemoteError as exc:
            detail = f"{exc.code}: {exc.message}" if exc.message else exc.code
            self._record_upload_failure(run_id, detail)
            logger.warning("Upload of backup run %s failed: %s", run_id, exc.code)
            return False
        except (StorageError, FileNotFoundError):
            self._record_upload_failure(run_id, "The local backup file no longer exists.")
            return False

        with self.session_factory() as db:
            run = BackupRunRepository(db).get(run_id)
            if run is None:
                # Deleted while uploading: do not leave an orphaned object behind.
                with contextlib.suppress(RemoteError):
                    storage.delete(key)
                return False
            run.remote_status = "success"
            run.remote_uploaded_at = utcnow()
            run.remote_deleted_at = None
            run.remote_error = None
            db.commit()
        logger.info("Backup run %s uploaded to remote storage", run_id)
        return True

    def apply_retention_for(self, run_id: int) -> None:
        with self.session_factory() as db:
            run = BackupRunRepository(db).get(run_id)
            if run is None or run.instance_id is None:
                return
            RetentionService(db, self.store).apply(
                instance_id=run.instance_id, database=run.database_name
            )


def wait_until_idle(runner: BackupRunner, timeout: float = 10.0) -> None:
    """Test helper: wait until no dump process is registered."""
    deadline = time.monotonic() + timeout
    while runner.active_pids() and time.monotonic() < deadline:
        time.sleep(0.05)
