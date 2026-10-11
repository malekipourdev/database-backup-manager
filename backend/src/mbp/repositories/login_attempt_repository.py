from sqlalchemy.orm import Session

from mbp.models import LoginAttempt


class LoginAttemptRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, username: str) -> LoginAttempt | None:
        return self.db.get(LoginAttempt, username)

    def upsert(self, attempt: LoginAttempt) -> LoginAttempt:
        merged = self.db.merge(attempt)
        self.db.flush()
        return merged

    def delete(self, username: str) -> None:
        attempt = self.get(username)
        if attempt is not None:
            self.db.delete(attempt)
