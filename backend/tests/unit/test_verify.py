import bz2
import gzip
import hashlib

import pytest

from mbp.backups.verify import verify

DUMP = b"CREATE TABLE t (id int);\n" * 1000 + b"\n-- Dump completed on 2026-10-11 12:00:00\n"


def write(tmp_path, compression, data=DUMP):
    path = tmp_path / "f"
    if compression == "gzip":
        path.write_bytes(gzip.compress(data))
    elif compression == "bzip2":
        path.write_bytes(bz2.compress(data))
    else:
        path.write_bytes(data)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("compression", ["gzip", "bzip2", "none"])
def test_valid_files_pass(tmp_path, compression):
    path, digest = write(tmp_path, compression)
    assert verify(path, compression, digest).ok


@pytest.mark.parametrize("compression", ["gzip", "bzip2", "none"])
def test_missing_marker(tmp_path, compression):
    path, digest = write(tmp_path, compression, b"CREATE TABLE t (id int);\n")
    result = verify(path, compression, digest)
    assert (result.ok, result.reason) == (False, "no_marker")


def test_checksum_mismatch(tmp_path):
    path, _ = write(tmp_path, "gzip")
    assert verify(path, "gzip", "0" * 64).reason == "checksum_mismatch"


@pytest.mark.parametrize("compression", ["gzip", "bzip2"])
def test_truncated_archive_is_corrupt(tmp_path, compression):
    path, _ = write(tmp_path, compression)
    path.write_bytes(path.read_bytes()[:-20])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert verify(path, compression, digest).reason == "corrupt"


def test_flipped_byte_is_corrupt(tmp_path):
    path, _ = write(tmp_path, "gzip")
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert verify(path, "gzip", digest).reason == "corrupt"
