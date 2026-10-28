"""Webhooks of the external API: addresses that receive events as signed JSON.

Managed from the panel and through the API itself (scope "webhooks"), so an integration can
subscribe its own endpoint. See mbp.apiaccess.webhooks for the delivery format.
"""

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import (
    WebhookDeliveryOut,
    WebhookFields,
    WebhookOut,
    WebhookSecret,
    WebhookUpdate,
)
from mbp.apiaccess.webhooks import ALL_EVENTS, EVENT_NAMES, WebhookDispatcher, generate_secret
from mbp.db import get_db, utcnow
from mbp.logging import register_secret
from mbp.models import ApiWebhook, ApiWebhookDelivery
from mbp.security import crypto

router = APIRouter(tags=["webhooks"])


def dispatcher(request: Request) -> WebhookDispatcher:
    return request.app.state.webhooks


def _events(events: list[str]) -> list[str]:
    wanted = {e.strip() for e in events}
    if ALL_EVENTS in wanted:
        return [ALL_EVENTS]
    bad = sorted(wanted - set(EVENT_NAMES))
    if bad:
        raise ApiError(422, "validation_error", detail=", ".join(bad), fields={"events": "unknown"})
    return [e for e in EVENT_NAMES if e in wanted]


def _hook(db: Session, webhook_id: int) -> ApiWebhook:
    hook = db.get(ApiWebhook, webhook_id)
    if hook is None:
        raise ApiError(404, "webhook_not_found")
    return hook


def _secret(hook: ApiWebhook, db: Session) -> WebhookSecret:
    secret = generate_secret()
    register_secret(secret)
    hook.secret_encrypted = crypto.encrypt(secret)
    db.commit()
    db.refresh(hook)
    return WebhookSecret(webhook=WebhookOut.model_validate(hook), secret=secret)


@router.get("/webhooks/-/events", response_model=list[str])
def events() -> list[str]:
    """Every event a webhook can subscribe to ("*" subscribes to all, now and future)."""
    return [ALL_EVENTS, *EVENT_NAMES]


@router.get("/webhooks", response_model=list[WebhookOut])
def list_webhooks(db: Session = Depends(get_db)) -> list[ApiWebhook]:
    return list(db.scalars(select(ApiWebhook).order_by(ApiWebhook.id)))


@router.post("/webhooks", response_model=WebhookSecret, status_code=201)
def create_webhook(body: WebhookFields, db: Session = Depends(get_db)) -> WebhookSecret:
    """Creates a webhook; the response holds its signing secret, shown this once."""
    hook = ApiWebhook(
        name=body.name,
        url=body.url,
        events=_events(body.events),
        enabled=body.enabled,
        secret_encrypted="",
        failures=0,
        created_at=utcnow(),
    )
    db.add(hook)
    db.flush()
    return _secret(hook, db)


@router.get("/webhooks/{webhook_id}", response_model=WebhookOut)
def get_webhook(webhook_id: int, db: Session = Depends(get_db)) -> ApiWebhook:
    return _hook(db, webhook_id)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
def update_webhook(
    webhook_id: int, body: WebhookUpdate, db: Session = Depends(get_db)
) -> ApiWebhook:
    hook = _hook(db, webhook_id)
    if body.name is not None:
        hook.name = body.name
    if body.url is not None:
        hook.url = body.url
    if body.events is not None:
        hook.events = _events(body.events)
    if body.enabled is not None:
        hook.enabled = body.enabled
        if body.enabled:
            hook.failures = 0
    db.commit()
    db.refresh(hook)
    return hook


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)) -> Response:
    db.delete(_hook(db, webhook_id))
    db.commit()
    return Response(status_code=204)


@router.post("/webhooks/{webhook_id}/rotate-secret", response_model=WebhookSecret)
def rotate_secret(webhook_id: int, db: Session = Depends(get_db)) -> WebhookSecret:
    """A new signing secret; the old one stops working at once."""
    return _secret(_hook(db, webhook_id), db)


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookDeliveryOut)
def test_webhook(
    webhook_id: int,
    db: Session = Depends(get_db),
    hooks: WebhookDispatcher = Depends(dispatcher),
) -> ApiWebhookDelivery:
    """Sends a "ping" event now and returns how it went (no retries)."""
    _hook(db, webhook_id)
    try:
        return hooks.ping(webhook_id)
    except LookupError:
        raise ApiError(404, "webhook_not_found") from None


@router.get("/webhooks/{webhook_id}/deliveries", response_model=list[WebhookDeliveryOut])
def deliveries(
    webhook_id: int,
    status: str | None = Query(default=None, pattern="^(pending|sent|failed)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[ApiWebhookDelivery]:
    """The latest deliveries, newest first (the last 200 are kept)."""
    _hook(db, webhook_id)
    stmt = select(ApiWebhookDelivery).where(ApiWebhookDelivery.webhook_id == webhook_id)
    if status:
        stmt = stmt.where(ApiWebhookDelivery.status == status)
    return list(db.scalars(stmt.order_by(ApiWebhookDelivery.id.desc()).limit(limit)))


@router.post("/webhooks/deliveries/{delivery_id}/redeliver", response_model=WebhookDeliveryOut)
def redeliver(
    delivery_id: int,
    db: Session = Depends(get_db),
    hooks: WebhookDispatcher = Depends(dispatcher),
) -> ApiWebhookDelivery:
    """Sends a delivery's payload again now, as a new delivery with a new ID."""
    if db.get(ApiWebhookDelivery, delivery_id) is None:
        raise ApiError(404, "delivery_not_found")
    try:
        return hooks.redeliver(delivery_id)
    except LookupError:
        raise ApiError(404, "delivery_not_found") from None
