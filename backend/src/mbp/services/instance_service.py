from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import InstanceCreate, InstanceUpdate
from mbp.logging import register_secret
from mbp.models import DbInstance
from mbp.repositories.instance_repository import InstanceRepository
from mbp.security import crypto
from mbp.services import mysql_probe
from mbp.services.mysql_probe import ConnParams, ProbeResult

CONNECTION_FIELDS = ("host", "port", "username", "password")


def get_decrypted_password(instance: DbInstance) -> str:
    """For internal use by the probe only; the value must never leave the backend."""
    password = crypto.decrypt(instance.password_encrypted)
    register_secret(password)
    return password


def conn_params(instance: DbInstance) -> ConnParams:
    return ConnParams(
        host=instance.host,
        port=instance.port,
        username=instance.username,
        password=get_decrypted_password(instance),
    )


def _clear_detection(instance: DbInstance) -> None:
    instance.server_type = None
    instance.server_version = None
    instance.last_test_at = None
    instance.last_test_ok = None
    instance.last_test_error_code = None


class InstanceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = InstanceRepository(db)

    def list(self) -> list[DbInstance]:
        return self.repo.list_ordered_by_name()

    def get(self, instance_id: int) -> DbInstance:
        instance = self.repo.get(instance_id)
        if instance is None:
            raise ApiError(404, "instance_not_found")
        return instance

    def create(self, data: InstanceCreate) -> DbInstance:
        self._ensure_name_free(data.name)
        password = data.password.get_secret_value()
        register_secret(password)
        instance = DbInstance(
            name=data.name,
            name_normalized=data.name.lower(),
            host=data.host,
            port=data.port,
            username=data.username,
            password_encrypted=crypto.encrypt(password),
            notes=data.notes,
        )
        self.repo.add(instance)
        self._commit()
        return instance

    def update(self, instance_id: int, data: InstanceUpdate) -> DbInstance:
        instance = self.get(instance_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        connection_changed = False

        if "name" in changes:
            self._ensure_name_free(changes["name"], exclude_id=instance.id)
            instance.name = changes["name"]
            instance.name_normalized = changes["name"].lower()
        for attr in ("host", "port", "username"):
            if attr in changes and changes[attr] != getattr(instance, attr):
                setattr(instance, attr, changes[attr])
                connection_changed = True
        if "notes" in changes:
            instance.notes = changes["notes"]
        if data.password is not None and data.password.get_secret_value():
            # Empty password means "keep the stored one".
            password = data.password.get_secret_value()
            register_secret(password)
            instance.password_encrypted = crypto.encrypt(password)
            connection_changed = True

        if connection_changed:
            _clear_detection(instance)
        self._commit()
        return instance

    def delete(self, instance_id: int) -> None:
        self.repo.delete(self.get(instance_id))
        self.db.commit()

    def test_saved(self, instance_id: int) -> ProbeResult:
        """Test a saved instance and record the outcome on it."""
        params = conn_params(self.get(instance_id))
        # Release the DB transaction while the (slow) network test runs.
        self.db.commit()
        result = mysql_probe.test_connection(params)

        instance = self.repo.get(instance_id)
        if instance is None:
            # Deleted while the test was running: discard the result.
            return result
        instance.last_test_at = result.tested_at
        instance.last_test_ok = result.ok
        instance.last_test_error_code = result.error_code
        if result.ok:
            instance.server_type = result.server_type
            instance.server_version = result.server_version
        self.db.commit()
        return result

    def _ensure_name_free(self, name: str, exclude_id: int | None = None) -> None:
        existing = self.repo.get_by_name_normalized(name.lower())
        if existing is not None and existing.id != exclude_id:
            raise ApiError(409, "name_taken", fields={"name": "name_taken"})

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            # Concurrent create/rename with the same name.
            self.db.rollback()
            raise ApiError(409, "name_taken", fields={"name": "name_taken"}) from exc
