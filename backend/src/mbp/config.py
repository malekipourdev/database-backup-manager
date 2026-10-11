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
    # A schedule that fires while the panel is down still runs if it starts within this time.
    schedule_misfire_grace_seconds: int = Field(default=300, ge=1)
    # Retention also runs after every backup; this periodic sweep catches age-based expiry.
    retention_interval_minutes: int = Field(default=60, ge=0)
    # How often stale backups and disk space are checked for alerts (0 = never).
    monitor_interval_minutes: int = Field(default=10, ge=0)
    # Master switch for the Bale/Telegram bots (e.g. off on a standby copy of the panel).
    bots_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
