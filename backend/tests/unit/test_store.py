from pathlib import PurePosixPath

import pytest

from mbp.backups.store import LocalBackupStore, StorageError


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    return LocalBackupStore(root)


def test_resolve_rejects_escapes(store, tmp_path):
    with pytest.raises(StorageError):
        store.resolve("../outside")
    with pytest.raises(StorageError):
        store.resolve("/etc/passwd")
    (tmp_path / "elsewhere").mkdir()
    (store.root / "link").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(StorageError):
        store.resolve("link/file.sql")


def test_prepare_creates_dirs_and_temp_name(store):
    relative, temp = store.prepare("daily", PurePosixPath("prod/shop.sql.gz"), 7)
    assert relative == "daily/prod/shop.sql.gz"
    assert temp.parent == store.root.resolve() / "daily" / "prod"
    assert temp.name == ".shop.sql.gz.7.mbp-partial"


def test_prepare_rejects_symlinked_directory(store, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (store.root / "evil").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(StorageError):
        store.prepare("evil", PurePosixPath("shop.sql"), 1)


def test_publish_never_overwrites(store):
    relative, temp = store.prepare("", PurePosixPath("shop.sql.gz"), 1)
    temp.write_bytes(b"first")
    assert store.publish(temp, relative) == "shop.sql.gz"
    assert not temp.exists()

    relative, temp = store.prepare("", PurePosixPath("shop.sql.gz"), 2)
    temp.write_bytes(b"second")
    assert store.publish(temp, relative) == "shop_2.sql.gz"
    assert (store.root / "shop.sql.gz").read_bytes() == b"first"
    assert (store.root / "shop_2.sql.gz").read_bytes() == b"second"


def test_cleanup_partials_only_removes_temp_files(store):
    (store.root / "a").mkdir()
    (store.root / "a" / ".x.sql.1.mbp-partial").write_bytes(b"x")
    (store.root / ".y.sql.2.mbp-partial").write_bytes(b"y")
    (store.root / "a" / "keep.sql.gz").write_bytes(b"k")
    assert store.cleanup_partials() == 2
    assert (store.root / "a" / "keep.sql.gz").exists()


def test_delete_and_exists(store):
    (store.root / "f.sql").write_bytes(b"x")
    assert store.exists("f.sql")
    store.delete("f.sql")
    assert not store.exists("f.sql")
    store.delete("f.sql")  # missing file is fine
    assert not store.exists("../../etc/passwd")
