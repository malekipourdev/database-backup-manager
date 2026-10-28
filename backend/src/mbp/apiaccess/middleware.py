"""Around every /api/v1 request: CORS for browser callers, rate-limit headers, the request log."""

import logging
import time

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mbp.apiaccess.service import cors_origins, record_request
from mbp.db import get_sessionmaker

logger = logging.getLogger(__name__)

V1_PREFIX = "/api/v1"
ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
ALLOW_HEADERS = "Authorization, Content-Type, X-API-Key, X-MBP-On-Behalf-Of"
EXPOSE_HEADERS = (
    "Content-Disposition, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset"
)


def is_v1(path: str) -> bool:
    return path == V1_PREFIX or path.startswith(V1_PREFIX + "/")


class ApiV1Middleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_v1(scope["path"]):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allowed = False
        if origin:
            origins = await run_in_threadpool(cors_origins.get, get_sessionmaker())
            allowed = "*" in origins or origin in origins
        if scope["method"] == "OPTIONS" and origin and "access-control-request-method" in headers:
            await self._preflight(send, origin if allowed else None)
            return

        state: dict = scope.setdefault("state", {})
        started = time.monotonic()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out = MutableHeaders(scope=message)
                if allowed and origin:
                    out["Access-Control-Allow-Origin"] = origin
                    out["Access-Control-Expose-Headers"] = EXPOSE_HEADERS
                    out.add_vary_header("Origin")
                rate = state.get("api_rate")
                if rate is not None:
                    limit, remaining, reset = rate
                    out["X-RateLimit-Limit"] = str(limit)
                    out["X-RateLimit-Remaining"] = str(remaining)
                    out["X-RateLimit-Reset"] = str(reset)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            key_id = state.get("api_key_id")
            if key_id is not None:
                try:
                    await run_in_threadpool(
                        record_request,
                        get_sessionmaker(),
                        key_id=key_id,
                        method=scope["method"],
                        path=scope["path"][len(V1_PREFIX) :] or "/",
                        status=status,
                        ip=state.get("api_ip", ""),
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error=state.get("api_error"),
                        on_behalf_of=state.get("api_on_behalf"),
                    )
                except Exception:  # the log must never break the response
                    logger.exception("Could not record an API request")

    @staticmethod
    async def _preflight(send: Send, origin: str | None) -> None:
        headers: list[tuple[bytes, bytes]] = [(b"vary", b"Origin")]
        if origin is not None:
            headers += [
                (b"access-control-allow-origin", origin.encode("latin-1")),
                (b"access-control-allow-methods", ALLOW_METHODS.encode()),
                (b"access-control-allow-headers", ALLOW_HEADERS.encode()),
                (b"access-control-max-age", b"600"),
            ]
        await send(
            {
                "type": "http.response.start",
                "status": 204 if origin is not None else 403,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": b""})
