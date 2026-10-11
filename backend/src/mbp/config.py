from functools import lru_cache

from pydantic import SecretStr
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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
