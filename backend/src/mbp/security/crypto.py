from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet

from mbp.config import get_settings


def _build(raw: str) -> MultiFernet:
    keys = [key.strip() for key in raw.split(",") if key.strip()]
    if not keys:
        raise RuntimeError("MBP_ENCRYPTION_KEY is missing or invalid")
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except (ValueError, TypeError) as exc:
        raise RuntimeError("MBP_ENCRYPTION_KEY is missing or invalid") from exc


@lru_cache
def _fernet() -> MultiFernet:
    return _build(get_settings().encryption_key.get_secret_value())


def validate_key() -> None:
    """Fail fast at startup if the encryption key is absent or malformed."""
    try:
        raw = get_settings().encryption_key.get_secret_value()
    except Exception as exc:  # missing env var -> settings validation error
        raise RuntimeError("MBP_ENCRYPTION_KEY is missing or invalid") from exc
    _build(raw)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
