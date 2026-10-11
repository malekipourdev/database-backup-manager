"""Generic JSON webhook channel, signed with HMAC-SHA256."""

import hashlib
import hmac
import json
from zoneinfo import ZoneInfo

import httpx

from mbp.notifications.events import Event
from mbp.notifications.render import render

TIMEOUT_SECONDS = 10


def payload(event: Event, created_at: str) -> dict:
    return {
        "event": event.type,
        "severity": event.severity,
        "subject": event.subject,
        "message": render(event, "en", ZoneInfo("UTC")),
        "params": event.params,
        "run_id": event.run_id,
        "created_at": created_at,
        "source": "mysql-backup-panel",
    }


def send(url: str, secret: str | None, body: dict, transport=None) -> str:
    """POST the event; returns "sent" or "failed: <reason>" (never raises)."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "mysql-backup-panel"}
    if secret:
        digest = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
        headers["X-MBP-Signature"] = f"sha256={digest}"
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            response = client.post(url, content=data, headers=headers)
    except httpx.HTTPError as exc:
        return f"failed: {type(exc).__name__}"
    if response.status_code >= 300:
        return f"failed: HTTP {response.status_code}"
    return "sent"
