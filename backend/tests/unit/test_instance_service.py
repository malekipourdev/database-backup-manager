import pytest
from pydantic import ValidationError

from mbp.api.errors import ApiError
from mbp.api.schemas import InstanceCreate, InstanceUpdate
from mbp.db import utcnow
from mbp.security import crypto
from mbp.services.instance_service import InstanceService


def make(**overrides) -> InstanceCreate:
    data = {
        "name": "prod",
        "host": "db.internal",
        "port": 3306,
        "username": "backup",
        "password": "s3cret",
        "notes": "",
    }
    data.update(overrides)
    return InstanceCreate(**data)


@pytest.fixture
def service(db):
    return InstanceService(db)


def test_create_trims_name_and_encrypts_password(service):
    instance = service.create(make(name="  prod  "))
    assert instance.name == "prod"
    assert instance.name_normalized == "prod"
    assert "s3cret" not in instance.password_encrypted
    assert crypto.decrypt(instance.password_encrypted) == "s3cret"


def test_name_uniqueness_is_case_insensitive(service):
    service.create(make(name="Prod"))
    with pytest.raises(ApiError) as info:
        service.create(make(name="PROD"))
    assert (info.value.status, info.value.code) == (409, "name_taken")


def test_rename_to_existing_name_rejected(service):
    service.create(make(name="a"))
    b = service.create(make(name="b"))
    with pytest.raises(ApiError):
        service.update(b.id, InstanceUpdate(name="A"))
    # Renaming to its own name in different case is fine.
    assert service.update(b.id, InstanceUpdate(name="B")).name == "B"


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_port_out_of_range_rejected(port):
    with pytest.raises(ValidationError):
        make(port=port)


def test_notes_limit():
    make(notes="x" * 2000)
    with pytest.raises(ValidationError):
        make(notes="x" * 2001)


@pytest.mark.parametrize("host", ["mysql://db", "db host", "db/path", "", "user@db", "  "])
def test_invalid_hosts_rejected(host):
    with pytest.raises(ValidationError):
        make(host=host)


@pytest.mark.parametrize(
    "host", ["db.internal", "10.0.0.5", "::1", "fe80::1", "host.docker.internal", "my_db-1"]
)
def test_valid_hosts_accepted(host):
    assert make(host=host).host == host


def test_non_latin_values_preserved(service):
    instance = service.create(make(name="سرور اصلی", username="کاربر", notes="یادداشت"))
    assert (instance.name, instance.username, instance.notes) == ("سرور اصلی", "کاربر", "یادداشت")


def _mark_tested(instance):
    instance.server_type = "mysql"
    instance.server_version = "8.4.3"
    instance.last_test_at = utcnow()
    instance.last_test_ok = True


def test_empty_password_on_update_keeps_ciphertext(service, db):
    instance = service.create(make())
    before = instance.password_encrypted
    service.update(instance.id, InstanceUpdate(password=""))
    service.update(instance.id, InstanceUpdate(notes="changed"))
    assert instance.password_encrypted == before


@pytest.mark.parametrize(
    "change",
    [{"host": "other"}, {"port": 3307}, {"username": "root"}, {"password": "new-pass"}],
)
def test_connection_change_clears_detection(service, db, change):
    instance = service.create(make())
    _mark_tested(instance)
    db.commit()
    service.update(instance.id, InstanceUpdate(**change))
    assert instance.server_type is None
    assert instance.server_version is None
    assert instance.last_test_at is None
    assert instance.last_test_ok is None


@pytest.mark.parametrize("change", [{"notes": "n"}, {"name": "renamed"}, {"host": "db.internal"}])
def test_non_connection_change_keeps_detection(service, db, change):
    instance = service.create(make())
    _mark_tested(instance)
    db.commit()
    service.update(instance.id, InstanceUpdate(**change))
    assert instance.server_type == "mysql"
    assert instance.last_test_ok is True


def test_get_unknown_raises_not_found(service):
    with pytest.raises(ApiError) as info:
        service.get(999)
    assert (info.value.status, info.value.code) == (404, "instance_not_found")
