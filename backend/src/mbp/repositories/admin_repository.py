from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mbp.db import utcnow
from mbp.models import AdminAccount


class AdminRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, admin_id: int) -> AdminAccount | None:
        return self.db.get(AdminAccount, admin_id)

    def get_by_username(self, username: str) -> AdminAccount | None:
        stmt = select(AdminAccount).where(AdminAccount.username == username.lower())
        return self.db.scalars(stmt).first()

    def count(self) -> int:
        return self.db.scalar(select(func.count()).select_from(AdminAccount)) or 0

    def create(self, username: str, password_hash: str) -> AdminAccount:
        admin = AdminAccount(username=username.lower(), password_hash=password_hash)
        self.db.add(admin)
        self.db.flush()
        return admin

    def update_password_hash(self, admin: AdminAccount, password_hash: str) -> None:
        admin.password_hash = password_hash

    def touch_last_login(self, admin: AdminAccount) -> None:
        admin.last_login_at = utcnow()
