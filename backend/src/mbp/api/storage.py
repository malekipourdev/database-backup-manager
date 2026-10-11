"""Remote storage settings, retention policies and on-demand retention."""

from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mbp.api.schemas import (
    InstanceStoragePolicyIn,
    InstanceStoragePolicyOut,
    RemoteStorageIn,
    RemoteStorageOut,
    RemoteTestOut,
    RetentionApplyRequest,
    RetentionItemOut,
    RetentionPolicyBody,
    RetentionReportOut,
)
from mbp.backups.store import get_store
from mbp.db import get_db
from mbp.models import RemoteStorageSettings
from mbp.repositories.backup_settings_repository import BackupSettingsRepository
from mbp.repositories.remote_storage_repository import RemoteStorageRepository
from mbp.services.instance_service import InstanceService
from mbp.services.remote_storage_service import (
    RemoteSettingsInput,
    RemoteStorageService,
    upload_enabled_for,
)
from mbp.services.retention_service import (
    EffectiveRetention,
    RetentionService,
    effective_retention,
    global_retention,
    instance_retention,
)

router = APIRouter(tags=["storage"])


def _remote_out(row: RemoteStorageSettings) -> RemoteStorageOut:
    return RemoteStorageOut(
        enabled=row.enabled,
        provider="s3",
        endpoint_url=row.endpoint_url,
        region=row.region,
        bucket=row.bucket,
        prefix=row.prefix,
        access_key_id=row.access_key_id,
        has_secret=bool(row.secret_access_key_encrypted),
        force_path_style=row.force_path_style,
    )


def _input(body: RemoteStorageIn) -> RemoteSettingsInput:
    return RemoteSettingsInput(
        enabled=body.enabled,
        endpoint_url=body.endpoint_url,
        region=body.region,
        bucket=body.bucket,
        prefix=body.prefix,
        access_key_id=body.access_key_id,
        secret_access_key=(
            body.secret_access_key.get_secret_value() if body.secret_access_key else None
        ),
        force_path_style=body.force_path_style,
    )


@router.get("/remote-storage", response_model=RemoteStorageOut)
def get_remote_storage_settings(db: Session = Depends(get_db)) -> RemoteStorageOut:
    return _remote_out(RemoteStorageService(db).get())


@router.put("/remote-storage", response_model=RemoteStorageOut)
def put_remote_storage_settings(
    body: RemoteStorageIn, db: Session = Depends(get_db)
) -> RemoteStorageOut:
    return _remote_out(RemoteStorageService(db).update(_input(body)))


@router.delete("/remote-storage/secret", response_model=RemoteStorageOut)
def delete_remote_storage_secret(db: Session = Depends(get_db)) -> RemoteStorageOut:
    return _remote_out(RemoteStorageService(db).clear_secret())


@router.post("/remote-storage/test", response_model=RemoteTestOut)
def test_remote_storage(body: RemoteStorageIn, db: Session = Depends(get_db)) -> RemoteTestOut:
    return RemoteTestOut(**asdict(RemoteStorageService(db).test(_input(body))))


def _policy_body(policy: EffectiveRetention) -> RetentionPolicyBody:
    return RetentionPolicyBody(
        local_keep_last=policy.local.keep_last,
        local_max_age_days=policy.local.max_age_days,
        remote_keep_last=policy.remote.keep_last,
        remote_max_age_days=policy.remote.max_age_days,
    )


@router.get("/retention", response_model=RetentionPolicyBody)
def get_retention(db: Session = Depends(get_db)) -> RetentionPolicyBody:
    return _policy_body(global_retention(db))


@router.put("/retention", response_model=RetentionPolicyBody)
def put_retention(body: RetentionPolicyBody, db: Session = Depends(get_db)) -> RetentionPolicyBody:
    repo = BackupSettingsRepository(db)
    current = repo.get()
    row = repo.save(current.storage_dir, current.name_pattern, current.compression)
    row.local_keep_last = body.local_keep_last
    row.local_max_age_days = body.local_max_age_days
    row.remote_keep_last = body.remote_keep_last
    row.remote_max_age_days = body.remote_max_age_days
    db.commit()
    return _policy_body(global_retention(db))


def _instance_policy(db: Session, instance_id: int) -> InstanceStoragePolicyOut:
    instance = InstanceService(db).get(instance_id)
    remote = RemoteStorageRepository(db).get()
    return InstanceStoragePolicyOut(
        remote_upload=instance.remote_upload or "inherit",  # type: ignore[arg-type]
        retention_override=instance.retention_override,
        retention=_policy_body(instance_retention(instance)),
        effective_upload=upload_enabled_for(remote, instance),
        effective_retention=_policy_body(effective_retention(db, instance)),
    )


@router.get("/instances/{instance_id}/storage-policy", response_model=InstanceStoragePolicyOut)
def get_instance_storage_policy(
    instance_id: int, db: Session = Depends(get_db)
) -> InstanceStoragePolicyOut:
    return _instance_policy(db, instance_id)


@router.put("/instances/{instance_id}/storage-policy", response_model=InstanceStoragePolicyOut)
def put_instance_storage_policy(
    instance_id: int, body: InstanceStoragePolicyIn, db: Session = Depends(get_db)
) -> InstanceStoragePolicyOut:
    instance = InstanceService(db).get(instance_id)
    instance.remote_upload = None if body.remote_upload == "inherit" else body.remote_upload
    instance.retention_override = body.retention_override
    instance.retention_local_keep_last = body.retention.local_keep_last
    instance.retention_local_max_age_days = body.retention.local_max_age_days
    instance.retention_remote_keep_last = body.retention.remote_keep_last
    instance.retention_remote_max_age_days = body.retention.remote_max_age_days
    db.commit()
    return _instance_policy(db, instance_id)


@router.post("/retention/apply", response_model=RetentionReportOut)
def apply_retention(
    body: RetentionApplyRequest, db: Session = Depends(get_db)
) -> RetentionReportOut:
    report = RetentionService(db, get_store()).apply(dry_run=body.dry_run)
    return RetentionReportOut(
        dry_run=report.dry_run,
        deleted=[RetentionItemOut(**asdict(item)) for item in report.deleted],
        errors=[RetentionItemOut(**asdict(item)) for item in report.errors],
    )
