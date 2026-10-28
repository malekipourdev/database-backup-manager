from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import (
    BackupRunOut,
    RunPage,
    RunStatus,
    StartAllRequest,
    StartBackupResponse,
    StartSingleRequest,
)
from mbp.api.scope import ServerScope, server_scope
from mbp.backups.remote import RemoteError
from mbp.backups.runner import BackupRunner
from mbp.backups.store import LocalBackupStore, StorageError, get_store
from mbp.db import get_db, utcnow
from mbp.models import BackupRun
from mbp.repositories.backup_run_repository import RunFilters
from mbp.services.backup_service import BackupService
from mbp.services.remote_storage_service import get_remote_storage

router = APIRouter(tags=["backups"])

MEDIA_TYPES = {
    "gzip": "application/gzip",
    "bzip2": "application/x-bzip2",
    "none": "application/sql",
}


def get_runner(request: Request) -> BackupRunner:
    return request.app.state.backup_runner


def run_out(run: BackupRun, store: LocalBackupStore) -> BackupRunOut:
    elapsed = None
    if run.status == "running" and run.started_at is not None:
        elapsed = int((utcnow() - run.started_at).total_seconds() * 1000)
    file_available = run.has_local_file and store.exists(run.file_path)
    return BackupRunOut(
        id=run.id,
        instance_id=run.instance_id,
        instance_name=run.instance_name,
        database_name=run.database_name,
        trigger=run.trigger,
        status=run.status,
        requested_at=run.requested_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        elapsed_ms=elapsed,
        bytes_processed=run.bytes_processed,
        file_size=run.file_size,
        compression=run.compression,
        checksum_sha256=run.checksum_sha256,
        file_name=PurePosixPath(run.file_path).name if run.file_path else None,
        file_available=file_available,
        server_type=run.server_type,
        server_version=run.server_version,
        error_code=run.error_code,
        error_message=run.error_message,
        schedule_id=run.schedule_id,
        file_deleted_at=run.file_deleted_at,
        file_deleted_reason=run.file_deleted_reason,
        remote_status=run.remote_status,
        remote_uploaded_at=run.remote_uploaded_at,
        remote_deleted_at=run.remote_deleted_at,
        remote_error=run.remote_error,
        remote_available=run.has_remote_copy,
        remote_deletable_at=run.remote_deletable_at,
        remote_deletable=run.remote_deletable(utcnow()),
        download_available=file_available or run.has_remote_copy,
    )


@router.post(
    "/instances/{instance_id}/backups", status_code=202, response_model=StartBackupResponse
)
def start_backup(
    instance_id: int,
    body: Annotated[StartAllRequest | StartSingleRequest, Body(discriminator="scope")],
    db: Session = Depends(get_db),
    runner: BackupRunner = Depends(get_runner),
) -> StartBackupResponse:
    store = get_store()
    database = body.database if isinstance(body, StartSingleRequest) else None
    created, skipped = BackupService(db, runner, store).start(instance_id, body.scope, database)
    return StartBackupResponse(
        created=[run_out(run, store) for run in created],
        skipped=skipped,
    )


@router.get("/backups/runs", response_model=RunPage)
def list_runs(
    instance_id: int | None = None,
    database: str | None = Query(default=None, max_length=64),
    status: list[RunStatus] | None = Query(default=None),
    requested_from: datetime | None = Query(default=None, alias="from"),
    requested_to: datetime | None = Query(default=None, alias="to"),
    sort: Literal[
        "requested_at", "duration_ms", "file_size", "instance_name", "database_name", "status"
    ] = "requested_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    scope: ServerScope | None = Depends(server_scope),
) -> RunPage:
    store = get_store()
    filters = RunFilters(
        instances=scope.instances() if scope else None,
        # Backups of deleted databases are listed with the panel's own server (not to a key
        # limited to some servers: they belong to no server any more).
        orphans=bool(scope and scope.local and not scope.restricted),
        instance_id=instance_id,
        database=database or None,
        statuses=list(status) if status else None,
        requested_from=requested_from,
        requested_to=requested_to,
    )
    items, total = BackupService(db, None, store).list(filters, sort, order, page, page_size)
    return RunPage(
        items=[run_out(run, store) for run in items], total=total, page=page, page_size=page_size
    )


@router.get("/backups/runs/{run_id}", response_model=BackupRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> BackupRunOut:
    store = get_store()
    return run_out(BackupService(db, None, store).get(run_id), store)


@router.delete("/backups/runs/{run_id}", status_code=204)
def delete_run(
    run_id: int,
    remote: bool = Query(default=False, description="Also delete the remote copy"),
    db: Session = Depends(get_db),
) -> Response:
    BackupService(db, None, get_store()).delete(run_id, delete_remote=remote)
    return Response(status_code=204)


@router.post("/backups/runs/{run_id}/upload", status_code=202, response_model=BackupRunOut)
def upload_run(
    run_id: int,
    db: Session = Depends(get_db),
    runner: BackupRunner = Depends(get_runner),
) -> BackupRunOut:
    store = get_store()
    run = BackupService(db, runner, store).retry_upload(run_id)
    return run_out(run, store)


def _attachment(filename: str) -> str:
    # RFC 6266/5987: an ASCII fallback plus the exact UTF-8 name.
    fallback = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{fallback}\"; filename*=utf-8''{quote(filename)}"


@router.get("/backups/runs/{run_id}/download", response_model=None)
def download_run(run_id: int, db: Session = Depends(get_db)) -> FileResponse | StreamingResponse:
    store = get_store()
    run = BackupService(db, None, store).get(run_id)
    if run.status != "success" or not run.file_path:
        raise ApiError(409, "file_unavailable")
    media_type = MEDIA_TYPES.get(run.compression or "none", "application/octet-stream")
    if run.has_local_file:
        try:
            path = store.path_for_download(run.file_path)
        except (StorageError, FileNotFoundError):
            path = None
        if path is not None:
            # FileResponse streams in chunks (constant memory) and supports Range requests.
            return FileResponse(
                path,
                media_type=media_type,
                filename=path.name,
                content_disposition_type="attachment",
            )
    if not run.has_remote_copy:
        raise ApiError(409, "file_unavailable")
    # The local file is gone (e.g. removed by retention): stream the remote copy instead.
    _, storage = get_remote_storage(db)
    if storage is None:
        raise ApiError(409, "remote_not_configured")
    key = run.remote_key or ""
    try:
        size = storage.size(key)
        chunks = storage.open_stream(key)
    except RemoteError as exc:
        raise ApiError(502, "remote_download_failed", detail=exc.code) from exc
    return StreamingResponse(
        chunks,
        media_type=media_type,
        headers={
            "Content-Disposition": _attachment(PurePosixPath(run.file_path).name),
            "Content-Length": str(size),
        },
    )
