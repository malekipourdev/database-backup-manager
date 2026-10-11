from sqlalchemy.orm import Session

from mbp.models import BackupSettings
from mbp.models.backup_settings import (
    DEFAULT_COMPRESSION,
    DEFAULT_NAME_PATTERN,
    DEFAULT_STORAGE_DIR,
)

SETTINGS_ID = 1


class BackupSettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> BackupSettings:
        """The settings row, or unsaved defaults if it is missing.

        Reads never insert: concurrent backup workers must not race to create the row.
        """
        settings = self.db.get(BackupSettings, SETTINGS_ID)
        if settings is None:
            return BackupSettings(
                id=SETTINGS_ID,
                storage_dir=DEFAULT_STORAGE_DIR,
                name_pattern=DEFAULT_NAME_PATTERN,
                compression=DEFAULT_COMPRESSION,
            )
        return settings

    def save(self, storage_dir: str, name_pattern: str, compression: str) -> BackupSettings:
        settings = self.db.get(BackupSettings, SETTINGS_ID)
        if settings is None:
            settings = BackupSettings(id=SETTINGS_ID)
            self.db.add(settings)
        settings.storage_dir = storage_dir
        settings.name_pattern = name_pattern
        settings.compression = compression
        self.db.flush()
        return settings
