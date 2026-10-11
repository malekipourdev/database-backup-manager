"""Post-write verification: checksum, full decompression and the dump completion marker."""

import bz2
import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
TAIL_BYTES = 4096
COMPLETION_MARKER = b"-- Dump completed"


@dataclass
class VerifyResult:
    ok: bool
    reason: str | None = None  # checksum_mismatch | corrupt | no_marker


def _raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _open_decompressed(path: Path, compression: str):
    if compression == "gzip":
        return gzip.open(path, "rb")
    if compression == "bzip2":
        return bz2.open(path, "rb")
    return open(path, "rb")


def verify(path: Path, compression: str, expected_sha256: str) -> VerifyResult:
    if _raw_sha256(path) != expected_sha256:
        return VerifyResult(False, "checksum_mismatch")
    tail = b""
    try:
        with _open_decompressed(path, compression) as stream:
            while chunk := stream.read(CHUNK_SIZE):
                tail = (tail + chunk)[-TAIL_BYTES:]
    except (OSError, EOFError, ValueError):
        # gzip.BadGzipFile is an OSError; truncated streams raise EOFError.
        return VerifyResult(False, "corrupt")
    if COMPLETION_MARKER not in tail:
        return VerifyResult(False, "no_marker")
    return VerifyResult(True)
