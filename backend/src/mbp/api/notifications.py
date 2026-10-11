from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import (
    EventInfo,
    NotificationLogItem,
    NotificationLogPage,
    NotificationRule,
    NotificationSettingsIn,
    NotificationSettingsOut,
    NotificationTestOut,
    NotificationTestRequest,
)
from mbp.backups.scheduler import parse_timezone
from mbp.db import get_db
from mbp.logging import register_secret
from mbp.models import NotificationLog, NotificationSettings
from mbp.notifications.events import EVENTS, Event, merged_rules
from mbp.repositories.notification_repository import NotificationRepository
from mbp.security import crypto

router = APIRouter(tags=["notifications"])


def _out(row: NotificationSettings) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        rules={k: NotificationRule(**v) for k, v in merged_rules(row.rules).items()},
        cooldown_minutes=row.cooldown_minutes,
        stale_hours=row.stale_hours,
        disk_free_percent=row.disk_free_percent,
        daily_summary_time=row.daily_summary_time,
        timezone=row.timezone,
        webhook_enabled=row.webhook_enabled,
        webhook_url=row.webhook_url,
        has_webhook_secret=bool(row.webhook_secret_encrypted),
        events=[EventInfo(name=name, severity=sev) for name, sev in EVENTS.items()],  # type: ignore[arg-type]
    )


@router.get("/notifications/settings", response_model=NotificationSettingsOut)
def get_notification_settings(db: Session = Depends(get_db)) -> NotificationSettingsOut:
    return _out(NotificationRepository(db).get_settings())


@router.put("/notifications/settings", response_model=NotificationSettingsOut)
def put_notification_settings(
    body: NotificationSettingsIn, request: Request, db: Session = Depends(get_db)
) -> NotificationSettingsOut:
    try:
        parse_timezone(body.timezone)
    except ValueError as exc:
        raise ApiError(422, "validation_error", fields={"timezone": "invalid_timezone"}) from exc
    if body.webhook_enabled and not body.webhook_url:
        raise ApiError(422, "validation_error", fields={"webhook_url": "required"})
    row = NotificationRepository(db).get_settings_for_update()
    row.rules = {
        name: {"enabled": rule.enabled, "channels": sorted(set(rule.channels))}
        for name, rule in body.rules.items()
    }
    row.cooldown_minutes = body.cooldown_minutes
    row.stale_hours = body.stale_hours
    row.disk_free_percent = body.disk_free_percent
    row.daily_summary_time = body.daily_summary_time
    row.timezone = body.timezone
    row.webhook_enabled = body.webhook_enabled
    row.webhook_url = body.webhook_url
    if body.clear_webhook_secret:
        row.webhook_secret_encrypted = None
    elif body.webhook_secret and body.webhook_secret.get_secret_value():
        secret = body.webhook_secret.get_secret_value()
        register_secret(secret)
        row.webhook_secret_encrypted = crypto.encrypt(secret)
    db.commit()
    scheduler = getattr(request.app.state, "backup_scheduler", None)
    if scheduler is not None:
        scheduler.sync_daily_summary()
    return _out(row)


@router.post("/notifications/test", response_model=NotificationTestOut)
def test_notifications(body: NotificationTestRequest, request: Request) -> NotificationTestOut:
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None:
        raise ApiError(503, "notifier_unavailable")
    log_id = notifier.emit(
        Event("test", "test", {}), channels=sorted(set(body.channels)), wait=True
    )
    with notifier.session_factory() as db:
        entry = db.get(NotificationLog, log_id) if log_id else None
        results = dict(entry.channels) if entry else {}
    return NotificationTestOut(results=results)


@router.get("/notifications/log", response_model=NotificationLogPage)
def notification_log(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    severity: str | None = Query(default=None, pattern="^(info|warning|error)$"),
    event: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
) -> NotificationLogPage:
    items, total = NotificationRepository(db).log_page(page, page_size, severity, event)
    return NotificationLogPage(
        items=[NotificationLogItem.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
