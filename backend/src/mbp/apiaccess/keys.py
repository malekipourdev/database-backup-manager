"""API keys: how they look, how a request is checked against one, and who it acts as."""

import hashlib
import ipaddress
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.apiaccess import scopes
from mbp.apiaccess.service import get_api_settings
from mbp.config import get_settings
from mbp.db import get_db, utcnow
from mbp.models import AdminAccount, ApiKey
from mbp.security.sessions import require_session

KEY_PREFIX = "mbp_"
# Characters of the secret shown in lists ("mbp_" and 8 more).
SHOWN = 12
ON_BEHALF_HEADER = "x-mbp-on-behalf-of"
ON_BEHALF_MAX = 120


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(secret: str) -> str:
    # The secret has 256 random bits: a plain hash cannot be brute-forced.
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def presented_key(request: Request) -> str | None:
    """`Authorization: Bearer <key>`, or `X-API-Key: <key>`."""
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return request.headers.get("x-api-key", "").strip() or None


def client_ip(request: Request) -> str:
    """The caller's address. Each proxy appends what it saw to X-Forwarded-For, so the entry
    added by the panel's own proxy (the last one, or earlier ones behind MBP_EXTRA_PROXY_HOPS
    more proxies) is the trustworthy one; entries before it are whatever the client sent."""
    forwarded = [
        part.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for part in header.split(",")
        if part.strip()
    ]
    if forwarded:
        return forwarded[max(len(forwarded) - 1 - get_settings().extra_proxy_hops, 0)]
    return request.client.host if request.client else ""


def ip_allowed(ip: str, allowed: list[str]) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowed:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


class RateLimiter:
    """Requests per key per minute (fixed one-minute windows, in this process)."""

    def __init__(self) -> None:
        self._windows: dict[int, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key_id: int, limit: int, now: float | None = None) -> tuple[bool, int, int]:
        """Counts a request: (allowed, remaining, seconds until the window resets)."""
        now = time.time() if now is None else now
        window = int(now // 60)
        reset = 60 - int(now % 60)
        with self._lock:
            start, count = self._windows.get(key_id, (window, 0))
            if start != window:
                count = 0
            if count >= limit:
                return False, 0, reset
            self._windows[key_id] = (window, count + 1)
            return True, limit - count - 1, reset

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()


limiter = RateLimiter()


def _refuse(request: Request, status: int, code: str, **kw) -> ApiError:
    request.state.api_error = code
    return ApiError(status, code, **kw)


def require_api_key(request: Request, db: Session = Depends(get_db)) -> ApiKey:
    """Authenticates an /api/v1 request and checks the key may make it."""
    secret = presented_key(request)
    if not secret:
        raise ApiError(401, "api_key_missing", headers={"WWW-Authenticate": "Bearer"})
    key = db.scalar(select(ApiKey).where(ApiKey.secret_hash == hash_key(secret)))
    if key is None:
        raise ApiError(401, "api_key_invalid", headers={"WWW-Authenticate": "Bearer"})
    # From here on the request is logged against the key, refused or not.
    request.state.api_key_id = key.id
    ip = client_ip(request)
    request.state.api_ip = ip
    request.state.api_on_behalf = on_behalf_of(request)
    if not get_api_settings(db).enabled:
        raise _refuse(request, 403, "api_disabled")
    if not key.enabled:
        raise _refuse(request, 403, "api_key_disabled")
    if key.expires_at is not None and key.expires_at <= utcnow():
        raise _refuse(request, 401, "api_key_expired")
    if key.allowed_ips and not ip_allowed(ip, key.allowed_ips):
        raise _refuse(request, 403, "ip_not_allowed", detail=ip)
    route = request.scope.get("route")
    tags = getattr(route, "tags", None) or []
    if tags and tags[0] in scopes.AREAS:
        needed = scopes.required_scope(request.method, tags[0], getattr(route, "path", ""))
        if not scopes.allows(key.scopes, needed):
            raise _refuse(request, 403, "insufficient_scope", detail=needed)
    if key.rate_limit > 0:
        allowed, remaining, reset = limiter.hit(key.id, key.rate_limit)
        request.state.api_rate = (key.rate_limit, remaining, reset)
        if not allowed:
            raise _refuse(request, 429, "rate_limited", headers={"Retry-After": str(reset)})
    admin = db.get(AdminAccount, key.admin_id)
    if admin is None:
        raise _refuse(request, 401, "api_key_invalid")
    request.state.api_key = key
    request.state.api_admin = admin
    request.state.api_servers = None if key.server_ids is None else frozenset(key.server_ids)
    return key


def on_behalf_of(request: Request) -> str | None:
    """`X-MBP-On-Behalf-Of`: the person the calling software acts for (its own user), which
    the panel only records: the key alone decides what the request may do. Headers carry
    ASCII only, so a name in another script is sent percent-encoded (UTF-8)."""
    raw = unquote(request.headers.get(ON_BEHALF_HEADER, ""), errors="replace")
    value = " ".join("".join(c for c in raw if c.isprintable()).split())
    return value[:ON_BEHALF_MAX] or None


@dataclass(frozen=True)
class Actor:
    """Who made a change, for the audit logs."""

    name: str
    # "panel" (signed in) or "api" (a key)
    source: str


def current_actor(request: Request, admin: AdminAccount = Depends(require_session)) -> Actor:
    key: ApiKey | None = getattr(request.state, "api_key", None)
    if key is None:
        return Actor(admin.username, "panel")
    person = on_behalf_of(request)
    if person:
        return Actor(f"{person} (API: {key.name})"[:100], "api")
    return Actor(f"{admin.username} (API: {key.name})"[:100], "api")
