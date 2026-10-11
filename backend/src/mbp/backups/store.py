"""Local filesystem storage for backup files, confined to the backup storage root."""

import contextlib
import errno
import itertools
import os
from functools import lru_cache
from pathlib import Path, PurePosixPath

from mbp.config import get_settings

PARTIAL_SUFFIX = ".mbp-partial"
# Hard links are unsupported on some filesystems (network shares, some FUSE mounts).
_NO_LINK_ERRNOS = {errno.EPERM, errno.EXDEV, errno.ENOTSUP, errno.EMLINK, errno.EOPNOTSUPP}


class StorageError(Exception):
    """A path is outside the storage root or cannot be used."""


def _split_extension(name: str) -> tuple[str, str]:
    index = name.find(".sql")
    return (name[:index], name[index:]) if index > 0 else (name, "")


class LocalBackupStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _resolved_root(self) -> Path:
        return self.root.resolve()

    def resolve(self, relative: str | PurePosixPath) -> Path:
        """Absolute path for a stored relative path; refuses anything outside the root."""
        root = self._resolved_root()
        path = (root / str(relative)).resolve()
        if path == root or not path.is_relative_to(root):
            raise StorageError("path is outside the backup storage area")
        return path

    def prepare(self, storage_dir: str, rendered: PurePosixPath, run_id: int) -> tuple[str, Path]:
        """Create the target directory; return (final relative path, temp file path)."""
        relative = PurePosixPath(storage_dir, rendered) if storage_dir else rendered
        final = self.resolve(relative)
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"cannot create directory: {exc.strerror}") from exc
        # Re-check after mkdir in case a component is a symlink leading outside the root.
        final = self.resolve(relative)
        temp = final.parent / f".{final.name}.{run_id}{PARTIAL_SUFFIX}"
        return str(relative), temp

    def publish(self, temp: Path, relative: str) -> str:
        """Give a verified temp file its final name without ever overwriting a file."""
        base = PurePosixPath(relative)
        stem, ext = _split_extension(base.name)
        for n in itertools.count(1):
            name = base.name if n == 1 else f"{stem}_{n}{ext}"
            candidate = str(base.with_name(name))
            target = self.resolve(candidate)
            try:
                os.link(temp, target)
            except FileExistsError:
                continue
            except OSError as exc:
                if exc.errno not in _NO_LINK_ERRNOS:
                    raise
                if target.exists():
                    continue
                os.replace(temp, target)
                return candidate
            temp.unlink(missing_ok=True)
            return candidate
        raise AssertionError("unreachable")

    def exists(self, relative: str | None) -> bool:
        if not relative:
            return False
        try:
            return self.resolve(relative).is_file()
        except StorageError:
            return False

    def path_for_download(self, relative: str) -> Path:
        path = self.resolve(relative)
        if not path.is_file():
            raise FileNotFoundError(relative)
        return path

    def delete(self, relative: str | None) -> None:
        if not relative:
            return
        with contextlib.suppress(StorageError):
            self.resolve(relative).unlink(missing_ok=True)

    @staticmethod
    def discard(temp: Path | None) -> None:
        if temp is not None:
            temp.unlink(missing_ok=True)

    def cleanup_partials(self) -> int:
        """Delete leftover temp files (from crashed or interrupted runs)."""
        root = self._resolved_root()
        if not root.is_dir():
            return 0
        removed = 0
        for path in root.rglob(f"*{PARTIAL_SUFFIX}"):
            if path.is_file():
                path.unlink(missing_ok=True)
                removed += 1
        return removed


@lru_cache
def get_store() -> LocalBackupStore:
    return LocalBackupStore(get_settings().backup_root)
