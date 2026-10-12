"""Authentication between the panel and an agent on another server.

The agent serves HTTPS with its own self-signed certificate. The panel pins that certificate
when the server is connected, after the agent proved it knows the server's token (`proof`).

Every request carries an HMAC of the method, the path, a timestamp and the fingerprint of
the certificate the panel trusts. The token itself never travels, and a signature made for
one certificate is refused by an agent with another one, so a machine in the middle can
neither learn the token nor pass a request on to the real agent.
"""

import hashlib
import hmac
import secrets
import time

SCHEME = "MBP-HMAC"
MAX_SKEW_SECONDS = 300
TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def fingerprint(der: bytes) -> str:
    """SHA-256 of a DER certificate, as lowercase hex."""
    return hashlib.sha256(der).hexdigest()


def _mac(token: str, message: str) -> str:
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def sign(token: str, method: str, path: str, cert_fp: str, ts: int | None = None) -> str:
    """The Authorization header value for one request."""
    ts = int(time.time()) if ts is None else ts
    mac = _mac(token, f"req\n{ts}\n{method.upper()}\n{path}\n{cert_fp}")
    return f"{SCHEME} ts={ts},sig={mac}"


def _timestamp(header: str) -> int | None:
    scheme, _, rest = header.partition(" ")
    if scheme != SCHEME:
        return None
    fields = dict(part.partition("=")[::2] for part in rest.split(","))
    try:
        return int(fields.get("ts", ""))
    except ValueError:
        return None


def clock_skewed(header: str, now: float | None = None) -> bool:
    ts = _timestamp(header)
    now = time.time() if now is None else now
    return ts is not None and abs(now - ts) > MAX_SKEW_SECONDS


def verify(
    header: str, token: str, method: str, path: str, cert_fp: str, now: float | None = None
) -> bool:
    ts = _timestamp(header)
    if ts is None:
        return False
    fields = dict(part.partition("=")[::2] for part in header.partition(" ")[2].split(","))
    now = time.time() if now is None else now
    if abs(now - ts) > MAX_SKEW_SECONDS:
        return False
    expected = _mac(token, f"req\n{ts}\n{method.upper()}\n{path}\n{cert_fp}")
    return hmac.compare_digest(fields.get("sig", ""), expected)


def proof(token: str, nonce: str, cert_fp: str) -> str:
    """The agent's answer to the panel's challenge: it knows the token and owns the cert."""
    return _mac(token, f"agent\n{nonce}\n{cert_fp}")
