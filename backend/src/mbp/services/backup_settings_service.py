from dataclasses import dataclass

from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.backups import naming
from mbp.db import utcnow
from mbp.models import DbInstance
from mbp.repositories.backup_settings_repository import BackupSettingsRepository
from mbp.services.instance_service import InstanceService


@dataclass(frozen=True)
class EffectiveSettings:
    storage_dir: str
    name_pattern: str
    compression: str


def _validation_errors(
    storage_dir: str | None, name_pattern: str | None, compression: str | None
) -> dict[str, str]:
    fields: dict[str, str] = {}
    if storage_dir is not None and (error := naming.validate_storage_dir(storage_dir)):
        fields["storage_dir"] = error
    if name_pattern is not None and (error := naming.validate_pattern(name_pattern)):
        fields["name_pattern"] = error
    if compression is not None and compression not in naming.COMPRESSIONS:
        fields["compression"] = "invalid_compression"
    return fields


def _raise_if_invalid(fields: dict[str, str]) -> None:
    if fields:
        raise ApiError(422, "validation_error", fields=fields)


def effective_for(db: Session, instance: DbInstance) -> EffectiveSettings:
    """Instance override where set, otherwise the global default."""
    defaults = BackupSettingsRepository(db).get()
    return EffectiveSettings(
        storage_dir=(
            instance.backup_storage_dir
            if instance.backup_storage_dir is not None
            else defaults.storage_dir
        ),
        name_pattern=instance.backup_name_pattern or defaults.name_pattern,
        compression=instance.backup_compression or defaults.compression,
    )


class BackupSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = BackupSettingsRepository(db)

    def get_global(self) -> EffectiveSettings:
        row = self.repo.get()
        self.db.commit()
        return EffectiveSettings(row.storage_dir, row.name_pattern, row.compression)

    def update_global(
        self, storage_dir: str, name_pattern: str, compression: str
    ) -> EffectiveSettings:
        storage_dir = storage_dir.strip()
        _raise_if_invalid(_validation_errors(storage_dir, name_pattern, compression))
        row = self.repo.save(storage_dir, name_pattern, compression)
        self.db.commit()
        return EffectiveSettings(row.storage_dir, row.name_pattern, row.compression)

    def preview(
        self,
        storage_dir: str,
        name_pattern: str,
        compression: str,
        instance_name: str,
        database_name: str,
    ) -> str:
        storage_dir = storage_dir.strip()
        _raise_if_invalid(_validation_errors(storage_dir, name_pattern, compression))
        rendered = naming.render(
            name_pattern,
            instance=instance_name,
            database=database_name,
            server_type="mysql",
            now=utcnow(),
            compression=compression,
        )
        return f"{storage_dir}/{rendered}" if storage_dir else str(rendered)

    def get_instance(self, instance_id: int) -> tuple[dict, EffectiveSettings]:
        instance = InstanceService(self.db).get(instance_id)
        overrides = {
            "storage_dir": instance.backup_storage_dir,
            "name_pattern": instance.backup_name_pattern,
            "compression": instance.backup_compression,
        }
        effective = effective_for(self.db, instance)
        self.db.commit()
        return overrides, effective

    def update_instance(
        self,
        instance_id: int,
        storage_dir: str | None,
        name_pattern: str | None,
        compression: str | None,
    ) -> tuple[dict, EffectiveSettings]:
        instance = InstanceService(self.db).get(instance_id)
        storage_dir = storage_dir.strip() if storage_dir is not None else None
        _raise_if_invalid(_validation_errors(storage_dir, name_pattern, compression))
        instance.backup_storage_dir = storage_dir
        instance.backup_name_pattern = name_pattern
        instance.backup_compression = compression
        self.db.commit()
        return self.get_instance(instance_id)
