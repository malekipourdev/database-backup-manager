"""Alerts: rules, cooldown, history, webhook (signed), bots by level, monitors, summary."""

import hashlib
import hmac
import json
import time
from collections import namedtuple
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from mbp.db import get_sessionmaker
from mbp.models import DbSelection, NotificationLog
from mbp.notifications.events import Event, level_allows, merged_rules
from mbp.notifications.monitor import AlertMonitor
from mbp.notifications.notifier import Notifier
from tests.conftest import BOT_ADMIN_ID, create_instance, wait_for_run, wait_until

WEBHOOK_SECRET = "Hook-Secret-42"


def settings_body(**overrides):
    body = {
        "rules": {},
        "cooldown_minutes": 60,
        "stale_hours": 26,
        "disk_free_percent": 10,
        "daily_summary_time": "08:00",
        "timezone": "Asia/Tehran",
        "webhook_enabled": False,
        "webhook_url": "",
    }
    body.update(overrides)
    return body


@pytest.fixture
def webhook(app):
    """Capture webhook deliveries in memory (the notifier posts through this transport)."""
    received: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200)

    app.state.notifier.webhook_transport = httpx.MockTransport(handle)
    return received


def enable_webhook(client, **overrides):
    body = settings_body(
        webhook_enabled=True,
        webhook_url="https://hooks.example.com/mbp",
        webhook_secret=WEBHOOK_SECRET,
        **overrides,
    )
    response = client.put("/api/notifications/settings", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def log(client, **params):
    return client.get("/api/notifications/log", params=params).json()["items"]


def wait_log(client, event, n=1):
    return wait_until(
        lambda: (
            (items := [i for i in log(client) if i["event"] == event]) and len(items) >= n and items
        ),
        message=f"{event} in the alert log",
    )


# --- rules ---


def test_level_filter():
    failed = Event("backup_failed", "s")
    success = Event("backup_succeeded", "s")
    summary = Event("daily_summary", "s")
    assert level_allows("warning", failed) and not level_allows("warning", success)
    assert level_allows("info", success)
    assert not level_allows("error", Event("disk_low", "s"))
    assert level_allows("error", summary)  # asked for explicitly
    assert not level_allows("off", failed)


def test_merged_rules_ignore_junk():
    rules = merged_rules(
        {"backup_failed": {"enabled": False, "channels": ["webhook", "sms"]}, "x": {}}
    )
    assert rules["backup_failed"] == {"enabled": False, "channels": ["webhook"]}
    assert "x" not in rules
    assert rules["disk_low"]["enabled"] is True


# --- settings API ---


def test_settings_roundtrip_and_secret(auth_client):
    initial = auth_client.get("/api/notifications/settings").json()
    assert initial["timezone"] == "Asia/Tehran"
    assert {e["name"] for e in initial["events"]} >= {"backup_failed", "stale_backup", "disk_low"}
    saved = enable_webhook(
        auth_client, rules={"backup_succeeded": {"enabled": False, "channels": []}}
    )
    assert saved["has_webhook_secret"] is True
    assert saved["rules"]["backup_succeeded"]["enabled"] is False
    assert WEBHOOK_SECRET not in json.dumps(saved)
    cleared = auth_client.put(
        "/api/notifications/settings",
        json=settings_body(clear_webhook_secret=True),
    ).json()
    assert cleared["has_webhook_secret"] is False


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"timezone": "Mars/Base"}, "timezone"),
        ({"daily_summary_time": "25:00"}, "daily_summary_time"),
        ({"webhook_enabled": True}, "webhook_url"),
        ({"webhook_url": "ftp://x"}, "webhook_url"),
        ({"rules": {"nope": {"enabled": True, "channels": []}}}, "rules.nope.[key]"),
    ],
)
def test_settings_validation(auth_client, overrides, field):
    response = auth_client.put("/api/notifications/settings", json=settings_body(**overrides))
    assert response.status_code == 422
    assert any(key.startswith(field.split(".")[0]) for key in response.json()["fields"])


# --- delivery ---


def test_webhook_test_button_is_signed(auth_client, webhook):
    enable_webhook(auth_client)
    result = auth_client.post("/api/notifications/test", json={"channels": ["webhook"]}).json()
    assert result == {"results": {"webhook": "sent"}}
    request = webhook[0]
    body = request.content
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert request.headers["X-MBP-Signature"] == f"sha256={expected}"
    payload = json.loads(body)
    assert payload["event"] == "test" and payload["source"] == "mysql-backup-panel"


def test_unconfigured_channels_are_reported(auth_client):
    result = auth_client.post(
        "/api/notifications/test", json={"channels": ["webhook", "bale", "telegram"]}
    ).json()["results"]
    assert result == {
        "webhook": "not_configured",
        "bale": "not_configured",
        "telegram": "not_configured",
    }


def test_backup_failure_alert_and_cooldown(auth_client, app, webhook, probe_ok):
    enable_webhook(auth_client)
    instance_id = create_instance(auth_client)

    def fail():
        run_id = auth_client.post(
            f"/api/instances/{instance_id}/backups",
            json={"scope": "single", "database": "denied_db"},
        ).json()["created"][0]["id"]
        wait_for_run(auth_client, run_id)
        return run_id

    first = fail()
    entry = wait_log(auth_client, "backup_failed")[0]
    assert entry["severity"] == "error"
    assert entry["run_id"] == first
    assert entry["params"]["db"] == "denied_db"
    assert entry["params"]["code"] == "missing_privileges"
    app.state.notifier.wait_idle()
    entry = log(auth_client, event="backup_failed")[0]
    assert entry["channels"]["webhook"] == "sent"
    payload = json.loads(webhook[0].content)
    assert payload["run_id"] == first and "denied_db" in payload["message"]

    # The same failure again within the cooldown is recorded but not sent.
    fail()
    entries = wait_log(auth_client, "backup_failed", 2)
    assert entries[0]["suppressed"] is True
    app.state.notifier.wait_idle()
    assert len([r for r in webhook if json.loads(r.content)["event"] == "backup_failed"]) == 1


def test_disabled_rule_raises_nothing(auth_client, webhook, probe_ok):
    enable_webhook(
        auth_client, rules={"backup_failed": {"enabled": False, "channels": ["webhook"]}}
    )
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "denied_db"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    time.sleep(0.3)
    assert log(auth_client, event="backup_failed") == []


def test_success_alert(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_shop"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    entry = wait_log(auth_client, "backup_succeeded")[0]
    assert entry["severity"] == "info" and entry["params"]["size"] > 0


def test_schedule_problem_alert(auth_client, app):
    instance_id = create_instance(auth_client)
    schedule = auth_client.post(
        f"/api/instances/{instance_id}/schedules",
        json={"name": "N", "cron": "0 2 * * *", "timezone": "UTC", "scope": "all"},
    ).json()
    assert app.state.backup_scheduler.fire(schedule["id"]) == "no_databases_selected"
    entry = wait_log(auth_client, "schedule_problem")[0]
    assert entry["params"] == {"name": "N", "instance": "prod", "result": "no_databases_selected"}


def test_bot_admins_get_alerts_by_level(auth_client, app, bale_bot, probe_ok):
    other = auth_client.post(
        "/api/bot-admins", json={"platform": "bale", "user_id": 222, "display_name": "Quiet"}
    ).json()
    auth_client.patch(f"/api/bot-admins/{other['id']}", json={"notify_level": "off"})
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "denied_db"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    message = wait_until(
        lambda: [m for m in bale_bot.calls("sendMessage") if "denied_db" in m["text"]],
        message="alert message",
    )[0]
    assert int(message["chat_id"]) == BOT_ADMIN_ID
    assert message["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"r:{run_id}"
    app.state.notifier.wait_idle()
    entry = log(auth_client, event="backup_failed")[0]
    assert entry["channels"]["bale"] == "sent: 1"
    assert entry["channels"]["telegram"] == "not_configured"
    assert all(int(m["chat_id"]) != 222 for m in bale_bot.calls("sendMessage"))


def test_bot_delivery_failure_is_recorded(auth_client, app, bale_bot):
    bale_bot.fail_send_to.add(BOT_ADMIN_ID)
    result = auth_client.post("/api/notifications/test", json={"channels": ["bale"]}).json()
    assert result["results"]["bale"].startswith("failed")


# --- monitors ---

Usage = namedtuple("Usage", "total used free")


def make_monitor(app, clock, free=50, total=100):
    notifier = Notifier(get_sessionmaker(), background=False, clock=clock)
    return AlertMonitor(
        get_sessionmaker(),
        notifier,
        "/backups",
        clock=clock,
        disk_usage=lambda path: Usage(total, total - free, free),
    )


def test_stale_backup_alerts_once_then_recovers(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client)
    with get_sessionmaker()() as db:
        db.add(
            DbSelection(
                instance_id=instance_id,
                database_name="ok_shop",
                created_at=datetime.now(UTC) - timedelta(hours=30),
            )
        )
        db.commit()
    monitor = make_monitor(app, lambda: datetime.now(UTC))
    events = monitor.check_stale()
    assert [e.type for e in events] == ["stale_backup"]
    assert events[0].params["hours"] == 26 and events[0].params["last_success"] is None
    assert monitor.check_stale() == []  # announced once while it lasts

    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_shop"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    recovered = monitor.check_stale()
    assert [(e.type, e.params["kind"]) for e in recovered] == [("recovered", "stale_backup")]


def test_new_selection_is_not_stale_yet(auth_client, app):
    create_instance(auth_client, select=("ok_shop",))
    assert make_monitor(app, lambda: datetime.now(UTC)).check_stale() == []


def test_disk_alert_and_recovery(app):
    now = lambda: datetime.now(UTC)  # noqa: E731
    low = make_monitor(app, now, free=4, total=100).check_disk()
    assert low.type == "disk_low" and low.severity == "error"  # under half the threshold
    assert make_monitor(app, now, free=4, total=100).check_disk() is None
    ok = make_monitor(app, now, free=40, total=100).check_disk()
    assert ok.type == "recovered" and ok.params["kind"] == "disk_low"
    warn = make_monitor(app, now, free=8, total=100).check_disk()
    assert warn.severity == "warning"


def test_daily_summary(auth_client, app, probe_ok):
    instance_id = create_instance(auth_client)
    for database in ("ok_shop", "denied_db"):
        run_id = auth_client.post(
            f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": database}
        ).json()["created"][0]["id"]
        wait_for_run(auth_client, run_id)
    summary = make_monitor(app, lambda: datetime.now(UTC), free=30).summary()
    assert (summary["ok"], summary["failed"]) == (1, 1)
    assert summary["failed_list"] == ["prod/denied_db"]
    assert summary["disk_free"] == 30


def test_log_paging_and_filter(auth_client, app):
    notifier = Notifier(get_sessionmaker(), background=False)
    for i in range(3):
        notifier.emit(
            Event("disk_low", f"d{i}", {"free_percent": 1, "free": 1, "total": 2, "threshold": 10})
        )
    notifier.emit(Event("backup_succeeded", "s", {"instance": "p", "db": "x", "size": 1}))
    page = auth_client.get("/api/notifications/log", params={"page_size": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    warnings = auth_client.get("/api/notifications/log", params={"severity": "warning"}).json()
    assert warnings["total"] == 3
    with get_sessionmaker()() as db:
        assert db.query(NotificationLog).count() == 4


def test_secrets_never_in_alerts(auth_client, app, webhook, probe_ok):
    enable_webhook(auth_client)
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "pwecho_db"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    wait_log(auth_client, "backup_failed")
    app.state.notifier.wait_idle()
    everything = json.dumps(log(auth_client)) + "".join(r.content.decode() for r in webhook)
    assert "Inst-Secret-77" not in everything
    assert WEBHOOK_SECRET not in everything
