"""Streams a dump subprocess through a compressor and a hasher into a file."""

import bz2
import contextlib
import gzip
import hashlib
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK_SIZE = 1024 * 1024
STDERR_TAIL_BYTES = 64 * 1024


class HashingWriter:
    """File-like writer that hashes and counts every byte written to the underlying file."""

    def __init__(self, target: BinaryIO) -> None:
        self.target = target
        self.sha256 = hashlib.sha256()
        self.size = 0

    def write(self, data: bytes) -> int:
        written = self.target.write(data)
        self.sha256.update(data)
        self.size += len(data)
        return written

    def flush(self) -> None:
        self.target.flush()

    def writable(self) -> bool:
        return True


@dataclass
class PipelineResult:
    returncode: int
    sha256: str
    size: int
    bytes_processed: int
    stderr_tail: str


def _compressor(writer: HashingWriter, compression: str):
    if compression == "gzip":
        # Level 6 matches the gzip tool's default; the empty filename keeps the
        # temp file name out of the gzip header.
        return gzip.GzipFile(filename="", fileobj=writer, mode="wb", compresslevel=6, mtime=0)
    if compression == "bzip2":
        return bz2.BZ2File(writer, mode="wb", compresslevel=9)
    return writer


class DumpProcess:
    def __init__(self, args: list[str], home: Path) -> None:
        self.args = args
        # Minimal environment: no inherited secrets, no MYSQL_PWD.
        self.env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home)}
        self.process: subprocess.Popen | None = None
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True
        process = self.process
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)

    def run(
        self,
        temp_path: Path,
        compression: str,
        on_progress: Callable[[int], None],
        interval: float,
    ) -> PipelineResult:
        with tempfile.TemporaryFile() as stderr_file:
            self.process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                self.args,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                env=self.env,
                start_new_session=True,
                close_fds=True,
            )
            if self.terminated:
                self.terminate()
            processed = 0
            try:
                with open(temp_path, "xb") as raw:
                    writer = HashingWriter(raw)
                    compressor = _compressor(writer, compression)
                    last_report = time.monotonic()
                    stdout = self.process.stdout
                    if stdout is None:
                        raise RuntimeError("dump process has no stdout pipe")
                    while chunk := stdout.read(CHUNK_SIZE):
                        compressor.write(chunk)
                        processed += len(chunk)
                        now = time.monotonic()
                        if now - last_report >= interval:
                            on_progress(processed)
                            last_report = now
                    if compressor is not writer:
                        compressor.close()  # flushes the trailer; does not close `raw`
                    raw.flush()
                    os.fsync(raw.fileno())
                returncode = self.process.wait()
            except BaseException:
                self.terminate()
                self.process.wait()
                raise
            finally:
                if self.process.stdout is not None:
                    self.process.stdout.close()
            on_progress(processed)
            stderr_file.seek(0, os.SEEK_END)
            stderr_file.seek(max(0, stderr_file.tell() - STDERR_TAIL_BYTES))
            stderr_tail = stderr_file.read().decode("utf-8", errors="replace")
        return PipelineResult(
            returncode=returncode,
            sha256=writer.sha256.hexdigest(),
            size=writer.size,
            bytes_processed=processed,
            stderr_tail=stderr_tail,
        )
