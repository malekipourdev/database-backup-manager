from sqlalchemy.orm import Session

from mbp.models import RemoteStorageSettings

SETTINGS_ID = 1


class RemoteStorageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> RemoteStorageSettings:
        """The settings row, or unsaved defaults if it is missing (reads never insert)."""
        row = self.db.get(RemoteStorageSettings, SETTINGS_ID)
        if row is None:
            return RemoteStorageSettings(
                id=SETTINGS_ID,
                enabled=False,
                provider="s3",
                endpoint_url="",
                region="",
                bucket="",
                prefix="",
                access_key_id="",
                secret_access_key_encrypted=None,
                force_path_style=True,
            )
        return row

    def get_for_update(self) -> RemoteStorageSettings:
        row = self.db.get(RemoteStorageSettings, SETTINGS_ID)
        if row is None:
            row = self.get()
            self.db.add(row)
        return row
