import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mbp.db import utcnow
from mbp.models import AuthSession

TOUCH_INTERVAL = timedelta(seconds=60)


def hash_token(plain_token: str) -> str:
    return hashlib.sha256(plain_token.encode("utf-8")).hexdigest()


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, admin_id: int) -> str:
        """Create a session and return the plain token (only its hash is stored)."""
        plain_token = secrets.token_urlsafe(32)
        self.db.add(AuthSession(token_hash=hash_token(plain_token), admin_id=admin_id))
        self.db.flush()
        return plain_token

    def get_valid(self, plain_token: str, idle_minutes: int) -> AuthSession | None:
        stmt = select(AuthSession).where(AuthSession.token_hash == hash_token(plain_token))
        session = self.db.scalars(stmt).first()
        if session is None:
            return None
        if utcnow() - session.last_activity_at >= timedelta(minutes=idle_minutes):
            return None
        return session

    def touch(self, session: AuthSession) -> bool:
        """Slide the idle window; writes at most once per minute. Returns True if updated."""
        now = utcnow()
        if now - session.last_activity_at >= TOUCH_INTERVAL:
            session.last_activity_at = now
            return True
        return False

    def delete(self, session: AuthSession) -> None:
        self.db.delete(session)

    def purge_expired(self, idle_minutes: int) -> None:
        cutoff = utcnow() - timedelta(minutes=idle_minutes)
        self.db.execute(delete(AuthSession).where(AuthSession.last_activity_at < cutoff))
