"""TOTP (RFC 6238) as used by Google Authenticator, plus one-time recovery codes."""

import hashlib
import hmac
import secrets
import time

import pyotp
import segno

ISSUER = "MySQL Backup Panel"
STEP_SECONDS = 30
# Accept the previous and next step too, for phones whose clock is a little off.
VALID_WINDOW = 1
RECOVERY_CODE_COUNT = 8
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_secret() -> str:
    return pyotp.random_base32()  # 160 bits, as Google Authenticator expects


def provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def qr_svg_data_uri(uri: str) -> str:
    """The provisioning URI as an inline SVG QR code (no external service sees the secret)."""
    return segno.make(uri, error="m").svg_data_uri(scale=6, border=2, dark="#000", light="#fff")


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step a 6-digit code belongs to (within the window), or None."""
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(secret)
    current = int((now if now is not None else time.time()) // STEP_SECONDS)
    for step in range(current - VALID_WINDOW, current + VALID_WINDOW + 1):
        if hmac.compare_digest(totp.at(step * STEP_SECONDS), code):
            return step
    return None


def verify(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """The accepted step, or None. A step at or before `last_step` was already used."""
    step = matching_step(secret, code, now)
    if step is None or (last_step is not None and step <= last_step):
        return None
    return step


def _normalize_recovery(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(_normalize_recovery(code).encode("utf-8")).hexdigest()


def new_recovery_codes() -> list[str]:
    """Codes like "k7m2-x9qp-4tdr" (60 bits each); shown once, stored as hashes."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def looks_like_recovery_code(code: str) -> bool:
    return len(_normalize_recovery(code)) == 12


def use_recovery_code(hashes: list[str] | None, code: str) -> list[str] | None:
    """The remaining hashes if `code` is one of them (it is used up), else None."""
    if not hashes or not looks_like_recovery_code(code):
        return None
    digest = hash_recovery_code(code)
    for stored in hashes:
        if hmac.compare_digest(stored, digest):
            return [h for h in hashes if h != stored]
    return None
