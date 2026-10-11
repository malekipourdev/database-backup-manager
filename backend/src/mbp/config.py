from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from MBP_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="MBP_")

    encryption_key: SecretStr
    admin_username: str | None = None
    admin_password: SecretStr | None = None
    database_url: str = "sqlite:////data/mbp.db"
    cookie_secure: bool = True
    session_idle_minutes: int = 30
    connect_timeout_seconds: int = 10
    backup_root: str = "/backups"
    backup_concurrency: int = Field(default=2, ge=1)
    mysqldump_path: str = "/usr/local/bin/mysqldump"
    mariadb_dump_path: str = "/usr/bin/mariadb-dump"
    backup_progress_interval_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
