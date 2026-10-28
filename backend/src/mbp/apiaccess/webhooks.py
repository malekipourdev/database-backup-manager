"""Webhooks of the external API: every event, as signed JSON, to the addresses subscribed to it.

Each POST carries:
  X-MBP-Event      the event name
  X-MBP-Delivery   a unique ID (also the payload's "id"); a retry keeps it
  X-MBP-Timestamp  Unix seconds when this attempt was signed
  X-MBP-Signature  "sha256=" + hex HMAC-SHA256 of "<timestamp>.<body>" with the webhook's secret

A delivery that fails (network error or a status other than 2xx) is retried twice, after
RETRY_DELAYS seconds.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from mbp.db import utcnow
from mbp.models import ApiWebhook, ApiWebhookDelivery
from mbp.notifications.events import EVENTS, Event
from mbp.notifications.render import render
from mbp.security import crypto

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10
RETRY_DELAYS: tuple[float, ...] = (10.0, 60.0)
# Deliveries kept per webhook.
KEEP_DELIVERIES = 200
ALL_EVENTS = "*"
# "ping" is sent by the test button only.
EVENT_NAMES: tuple[str, ...] = (*EVENTS, "ping")
SOURCE = "devops-manager"


def generate_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = str(timestamp).encode("ascii") + b"." + body
    return "sha256=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def subscribed(webhook: ApiWebhook, event: str) -> bool:
    return ALL_EVENTS in webhook.events or event in webhook.events


def event_payload(delivery_id: str, event: Event, created_at: datetime) -> dict:
    return {
        "id": delivery_id,
        "event": event.type,
        "created_at": created_at.isoformat(),
        "severity": event.severity,
        "subject": event.subject,
        "message": (
            "Test delivery from DevOps Manager."
            if event.type == "ping"
            else render(event, "en", ZoneInfo("UTC"))
        ),
        "params": event.params,
        "run_id": event.run_id,
        "source": SOURCE,
    }


class WebhookDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        background: bool = True,
        transport: httpx.BaseTransport | None = None,
        retry_delays: Sequence[float] = RETRY_DELAYS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.session_factory = session_factory
        self.transport = transport
        self.retry_delays = tuple(retry_delays)
        self.sleep = sleep
        self._executor = (
            ThreadPoolExecutor(max_workers=4, thread_name_prefix="mbp-webhook")
            if background
            else None
        )

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def dispatch(self, event: Event, created_at: datetime | None = None) -> list[int]:
        """Queues the event for every enabled webhook subscribed to it; returns delivery IDs.

        Never raises: a webhook problem must not break what raised the event.
        """
        try:
            created_at = created_at or utcnow()
            with self.session_factory() as db:
                hooks = db.scalars(select(ApiWebhook).where(ApiWebhook.enabled.is_(True))).all()
                ids = [
                    self._create(db, hook, event, created_at)
                    for hook in hooks
                    if subscribed(hook, event.type)
                ]
                db.commit()
        except Exception:
            logger.exception("Could not queue webhooks for %s", event.type)
            return []
        for delivery_id in ids:
            if self._executor is None:
                self._run_quietly(delivery_id)
            else:
                self._executor.submit(self._run_quietly, delivery_id)
        return ids

    def ping(self, webhook_id: int) -> ApiWebhookDelivery:
        """Sends a "ping" event now (one attempt) and returns the delivery."""
        with self.session_factory() as db:
            hook = db.get(ApiWebhook, webhook_id)
            if hook is None:
                raise LookupError(webhook_id)
            event = Event("ping", f"ping:{webhook_id}", {"webhook": hook.name})
            delivery_id = self._create(db, hook, event, utcnow())
            db.commit()
        return self._run(delivery_id, retries=False)

    def redeliver(self, delivery_id: int) -> ApiWebhookDelivery:
        """Sends a stored delivery's payload again, as a new delivery (one attempt)."""
        with self.session_factory() as db:
            old = db.get(ApiWebhookDelivery, delivery_id)
            if old is None:
                raise LookupError(delivery_id)
            new_id = str(uuid.uuid4())
            row = ApiWebhookDelivery(
                webhook_id=old.webhook_id,
                uuid=new_id,
                created_at=utcnow(),
                event=old.event,
                payload={**old.payload, "id": new_id},
                status="pending",
                attempts=0,
            )
            db.add(row)
            db.commit()
            new = row.id
        return self._run(new, retries=False)

    # --- internals ---

    @staticmethod
    def _create(db: Session, hook: ApiWebhook, event: Event, created_at: datetime) -> int:
        delivery_id = str(uuid.uuid4())
        row = ApiWebhookDelivery(
            webhook_id=hook.id,
            uuid=delivery_id,
            created_at=created_at,
            event=event.type,
            payload=event_payload(delivery_id, event, created_at),
            status="pending",
            attempts=0,
        )
        db.add(row)
        db.flush()
        return row.id

    def _run_quietly(self, delivery_id: int) -> None:
        try:
            self._run(delivery_id, retries=True)
        except LookupError:
            pass
        except Exception:
            logger.exception("Webhook delivery %s failed", delivery_id)

    def _run(self, delivery_id: int, retries: bool) -> ApiWebhookDelivery:
        delays = self.retry_delays if retries else ()
        row: ApiWebhookDelivery | None = None
        for attempt in range(len(delays) + 1):
            if attempt:
                self.sleep(delays[attempt - 1])
            row = self._attempt(delivery_id, final=attempt == len(delays))
            if row is None or row.status == "sent":
                break
        if row is None:  # the webhook or the delivery was deleted meanwhile
            raise LookupError(delivery_id)
        return row

    def _attempt(self, delivery_id: int, final: bool = True) -> ApiWebhookDelivery | None:
        with self.session_factory() as db:
            row = db.get(ApiWebhookDelivery, delivery_id)
            if row is None:
                return None
            hook = db.get(ApiWebhook, row.webhook_id)
            if hook is None:
                return None
            url = hook.url
            secret = crypto.decrypt(hook.secret_encrypted)
            body = json.dumps(row.payload, ensure_ascii=False).encode("utf-8")
            event, uuid_ = row.event, row.uuid
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": SOURCE,
            "X-MBP-Event": event,
            "X-MBP-Delivery": uuid_,
            "X-MBP-Timestamp": str(timestamp),
            "X-MBP-Signature": sign(secret, timestamp, body),
        }
        started = time.monotonic()
        response_status: int | None = None
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=self.transport) as client:
                response = client.post(url, content=body, headers=headers)
            response_status = response.status_code
            ok = 200 <= response.status_code < 300
            detail = None if ok else (response.text or f"HTTP {response.status_code}")[:300]
        except httpx.HTTPError as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:300]
        except Exception as exc:  # a malformed URL and the like
            ok, detail = False, f"{type(exc).__name__}"[:300]
        duration = int((time.monotonic() - started) * 1000)
        now = utcnow()
        with self.session_factory() as db:
            row = db.get(ApiWebhookDelivery, delivery_id)
            hook = db.get(ApiWebhook, row.webhook_id) if row is not None else None
            if row is None or hook is None:
                return None
            row.attempts += 1
            row.status = "sent" if ok else "failed"
            row.response_status = response_status
            row.detail = detail
            row.duration_ms = duration
            row.finished_at = now
            hook.last_delivery_at = now
            if ok:
                hook.failures = 0
            elif final:
                hook.failures += 1
            if ok:
                hook.last_status = f"HTTP {response_status}"
            else:
                hook.last_status = (
                    f"HTTP {response_status}" if response_status else (detail or "failed")
                )[:100]
            self._prune(db, hook.id)
            db.commit()
            db.refresh(row)
            db.expunge(row)
            return row

    @staticmethod
    def _prune(db: Session, webhook_id: int) -> None:
        cutoff = db.scalar(
            select(ApiWebhookDelivery.id)
            .where(ApiWebhookDelivery.webhook_id == webhook_id)
            .order_by(ApiWebhookDelivery.id.desc())
            .offset(KEEP_DELIVERIES)
            .limit(1)
        )
        if cutoff is not None:
            db.execute(
                delete(ApiWebhookDelivery).where(
                    ApiWebhookDelivery.webhook_id == webhook_id,
                    ApiWebhookDelivery.id <= cutoff,
                )
            )
