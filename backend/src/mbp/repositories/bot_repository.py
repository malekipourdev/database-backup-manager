from sqlalchemy import select
from sqlalchemy.orm import Session

from mbp.models import BotAdmin, BotLinkCode, BotSettings
from mbp.models.bot import PLATFORMS

DEFAULT_MAX_MB = {"bale": 20, "telegram": 50}


class BotRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self, platform: str) -> BotSettings:
        """The platform's row, or unsaved defaults if it is missing (reads never insert)."""
        row = self.db.get(BotSettings, platform)
        if row is None:
            return BotSettings(
                platform=platform,
                enabled=False,
                token_encrypted=None,
                api_base_url="",
                proxy_url="",
                allow_file_download=False,
                max_file_mb=DEFAULT_MAX_MB[platform],
            )
        return row

    def get_settings_for_update(self, platform: str) -> BotSettings:
        row = self.db.get(BotSettings, platform)
        if row is None:
            row = self.get_settings(platform)
            self.db.add(row)
        return row

    def all_settings(self) -> list[BotSettings]:
        return [self.get_settings(platform) for platform in PLATFORMS]

    def admins(self, platform: str | None = None) -> list[BotAdmin]:
        stmt = select(BotAdmin).order_by(BotAdmin.platform, BotAdmin.display_name, BotAdmin.id)
        if platform is not None:
            stmt = stmt.where(BotAdmin.platform == platform)
        return list(self.db.scalars(stmt))

    def admin(self, admin_id: int) -> BotAdmin | None:
        return self.db.get(BotAdmin, admin_id)

    def admin_by_user(self, platform: str, user_id: int) -> BotAdmin | None:
        stmt = select(BotAdmin).where(BotAdmin.platform == platform, BotAdmin.user_id == user_id)
        return self.db.scalars(stmt).first()

    def link_code(self, platform: str, code_hash: str) -> BotLinkCode | None:
        stmt = select(BotLinkCode).where(
            BotLinkCode.platform == platform, BotLinkCode.code_hash == code_hash
        )
        return self.db.scalars(stmt).first()
