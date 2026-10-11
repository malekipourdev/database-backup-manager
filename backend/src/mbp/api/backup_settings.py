from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mbp.api.schemas import (
    BackupSettingsBody,
    InstanceBackupOverrides,
    InstanceBackupSettings,
    PatternPreview,
    PatternPreviewRequest,
)
from mbp.db import get_db
from mbp.services.backup_settings_service import BackupSettingsService

router = APIRouter(tags=["backup-settings"])


@router.get("/backup-settings", response_model=BackupSettingsBody)
def get_backup_settings(db: Session = Depends(get_db)) -> BackupSettingsBody:
    return BackupSettingsBody(**asdict(BackupSettingsService(db).get_global()))


@router.put("/backup-settings", response_model=BackupSettingsBody)
def put_backup_settings(
    body: BackupSettingsBody, db: Session = Depends(get_db)
) -> BackupSettingsBody:
    saved = BackupSettingsService(db).update_global(
        body.storage_dir, body.name_pattern, body.compression
    )
    return BackupSettingsBody(**asdict(saved))


@router.post("/backup-settings/preview", response_model=PatternPreview)
def preview_pattern(body: PatternPreviewRequest, db: Session = Depends(get_db)) -> PatternPreview:
    path = BackupSettingsService(db).preview(
        body.storage_dir,
        body.name_pattern,
        body.compression,
        body.instance_name,
        body.database_name,
    )
    return PatternPreview(path=path)


def _instance_settings(overrides: dict, effective) -> InstanceBackupSettings:
    return InstanceBackupSettings(
        overrides=InstanceBackupOverrides(**overrides),
        effective=BackupSettingsBody(**asdict(effective)),
    )


@router.get("/instances/{instance_id}/backup-settings", response_model=InstanceBackupSettings)
def get_instance_backup_settings(
    instance_id: int, db: Session = Depends(get_db)
) -> InstanceBackupSettings:
    return _instance_settings(*BackupSettingsService(db).get_instance(instance_id))


@router.put("/instances/{instance_id}/backup-settings", response_model=InstanceBackupSettings)
def put_instance_backup_settings(
    instance_id: int, body: InstanceBackupOverrides, db: Session = Depends(get_db)
) -> InstanceBackupSettings:
    result = BackupSettingsService(db).update_instance(
        instance_id, body.storage_dir, body.name_pattern, body.compression
    )
    return _instance_settings(*result)
