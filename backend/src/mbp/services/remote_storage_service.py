from dataclasses import dataclass

from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.backups.remote import RemoteError, RemoteStorage, S3Config, S3RemoteStorage
from mbp.logging import register_secret
from mbp.models import DbInstance, RemoteStorageSettings
from mbp.repositories.remote_storage_repository import RemoteStorageRepository
from mbp.security import crypto


@dataclass(frozen=True)
class RemoteSettingsInput:
    enabled: bool
    endpoint_url: str
    region: str
    bucket: str
    prefix: str
    access_key_id: str
    # None or "" keeps the stored secret.
    secret_access_key: str | None
    force_path_style: bool


@dataclass(frozen=True)
class RemoteTestResult:
    ok: bool
    error_code: str | None = None
    error_detail: str | None = None


def is_configured(row: RemoteStorageSettings) -> bool:
    return bool(row.bucket and row.access_key_id and row.secret_access_key_encrypted)


def upload_enabled_for(row: RemoteStorageSettings, instance: DbInstance | None) -> bool:
    """Instance setting where set ("enabled"/"disabled"), otherwise the global switch."""
    if not is_configured(row):
        return False
    choice = instance.remote_upload if instance is not None else None
    if choice == "enabled":
        return True
    if choice == "disabled":
        return False
    return bool(row.enabled)


def _decrypted_secret(row: RemoteStorageSettings) -> str:
    secret = crypto.decrypt(row.secret_access_key_encrypted or "")
    register_secret(secret)
    return secret


def _storage(
    endpoint_url: str,
    region: str,
    bucket: str,
    prefix: str,
    access_key_id: str,
    secret: str,
    force_path_style: bool,
) -> S3RemoteStorage:
    return S3RemoteStorage(
        S3Config(
            bucket=bucket,
            access_key_id=access_key_id,
            secret_access_key=secret,
            endpoint_url=endpoint_url,
            region=region,
            prefix=prefix,
            force_path_style=force_path_style,
        )
    )


def storage_from(row: RemoteStorageSettings) -> RemoteStorage | None:
    """The configured remote storage, or None if it is not fully configured."""
    if not is_configured(row):
        return None
    return _storage(
        row.endpoint_url,
        row.region,
        row.bucket,
        row.prefix,
        row.access_key_id,
        _decrypted_secret(row),
        row.force_path_style,
    )


def get_remote_storage(db: Session) -> tuple[RemoteStorageSettings, RemoteStorage | None]:
    row = RemoteStorageRepository(db).get()
    return row, storage_from(row)


class RemoteStorageService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RemoteStorageRepository(db)

    def get(self) -> RemoteStorageSettings:
        row = self.repo.get()
        self.db.commit()
        return row

    def update(self, data: RemoteSettingsInput) -> RemoteStorageSettings:
        row = self.repo.get_for_update()
        secret_set = bool(data.secret_access_key) or bool(row.secret_access_key_encrypted)
        fields: dict[str, str] = {}
        if data.enabled:
            if not data.bucket:
                fields["bucket"] = "required"
            if not data.access_key_id:
                fields["access_key_id"] = "required"
            if not secret_set:
                fields["secret_access_key"] = "required"  # noqa: S105 - error code
        if fields:
            raise ApiError(422, "validation_error", fields=fields)
        row.enabled = data.enabled
        row.endpoint_url = data.endpoint_url
        row.region = data.region
        row.bucket = data.bucket
        row.prefix = data.prefix
        row.access_key_id = data.access_key_id
        row.force_path_style = data.force_path_style
        if data.secret_access_key:
            register_secret(data.secret_access_key)
            row.secret_access_key_encrypted = crypto.encrypt(data.secret_access_key)
        self.db.commit()
        return row

    def clear_secret(self) -> RemoteStorageSettings:
        row = self.repo.get_for_update()
        row.secret_access_key_encrypted = None
        row.enabled = False
        self.db.commit()
        return row

    def test(self, data: RemoteSettingsInput) -> RemoteTestResult:
        """Test the given (possibly unsaved) values; an empty secret uses the stored one."""
        if data.secret_access_key:
            secret = data.secret_access_key
            register_secret(secret)
        else:
            row = self.repo.get()
            if not row.secret_access_key_encrypted:
                raise ApiError(422, "validation_error", fields={"secret_access_key": "required"})
            secret = _decrypted_secret(row)
        # Release the DB transaction while the (slow) network test runs.
        self.db.commit()
        storage = _storage(
            data.endpoint_url,
            data.region,
            data.bucket,
            data.prefix,
            data.access_key_id,
            secret,
            data.force_path_style,
        )
        try:
            storage.check()
        except RemoteError as exc:
            return RemoteTestResult(ok=False, error_code=exc.code, error_detail=exc.message)
        return RemoteTestResult(ok=True)
