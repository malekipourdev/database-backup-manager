"""Stored state of the external API: its settings and the request log."""

import itertools
import threading
import time
from datetime import timedelta

from sqlalchemy import delete, update
from sqlalchemy.orm import Session, sessionmaker

from mbp.db import utcnow
from mbp.models import ApiKey, ApiRequestLog, ApiSettings

# The log is pruned every this many requests.
PRUNE_EVERY = 200


def get_api_settings(db: Session) -> ApiSettings:
    row = db.get(ApiSettings, 1)
    if row is None:
        row = ApiSettings(id=1, enabled=True, cors_origins=[], log_retention_days=30)
        db.add(row)
        db.flush()
    return row


class CorsOrigins:
    """The allowed browser origins, read at most every few seconds."""

    TTL_SECONDS = 5.0

    def __init__(self) -> None:
        self._origins: list[str] = []
        self._read_at = float("-inf")
        self._lock = threading.Lock()

    def get(self, session_factory: sessionmaker[Session]) -> list[str]:
        with self._lock:
            if time.monotonic() - self._read_at < self.TTL_SECONDS:
                return self._origins
        with session_factory() as db:
            origins = list(get_api_settings(db).cors_origins or [])
            db.commit()
        with self._lock:
            self._origins, self._read_at = origins, time.monotonic()
        return origins

    def forget(self) -> None:
        with self._lock:
            self._read_at = float("-inf")


cors_origins = CorsOrigins()
_counter = itertools.count(1)


def record_request(
    session_factory: sessionmaker[Session],
    *,
    key_id: int,
    method: str,
    path: str,
    status: int,
    ip: str,
    duration_ms: int,
    error: str | None,
) -> None:
    now = utcnow()
    with session_factory() as db:
        db.add(
            ApiRequestLog(
                key_id=key_id,
                created_at=now,
                method=method[:8],
                path=path[:300],
                status=status,
                ip=ip[:45],
                duration_ms=duration_ms,
                error=error[:64] if error else None,
            )
        )
        db.execute(
            update(ApiKey)
            .where(ApiKey.id == key_id)
            .values(
                last_used_at=now,
                last_used_ip=ip[:45] or None,
                request_count=ApiKey.request_count + 1,
            )
        )
        if next(_counter) % PRUNE_EVERY == 0:
            days = get_api_settings(db).log_retention_days
            db.execute(
                delete(ApiRequestLog).where(ApiRequestLog.created_at < now - timedelta(days=days))
            )
        db.commit()
