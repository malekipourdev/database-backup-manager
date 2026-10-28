"""Webhooks of the external API: management, signed deliveries, retries, the notifier's events."""

import hashlib
import hmac
import json

import httpx
import pytest

from mbp.apiaccess.keys import limiter
from mbp.apiaccess.webhooks import WebhookDispatcher
from mbp.db import get_sessionmaker
from mbp.models import ApiWebhookDelivery, NotificationLog
from mbp.notifications.events import Event
from mbp.notifications.notifier import Notifier
from tests.api.test_external_api import bearer, make_key


class Receiver:
    """An HTTP endpoint answering with the given statuses in turn (the last one repeats)."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses) or [200]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses[min(len(self.requests) - 1, len(self.statuses) - 1)]
        return httpx.Response(status, text="nope" if status >= 300 else "ok")

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def receiver(app, client):
    """The app's dispatcher, delivering synchronously to a mock receiver."""
    limiter.clear()
    rx = Receiver()
    app.state.webhooks = WebhookDispatcher(
        get_sessionmaker(), background=False, transport=rx.transport, sleep=lambda _: None
    )
    return rx


def create(client, **fields) -> dict:
    body = {"name": "erp", "url": "https://hooks.example.com/mbp", "events": ["*"], **fields}
    response = client.post("/api/webhooks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def check_signature(secret: str, request: httpx.Request) -> None:
    timestamp = request.headers["X-MBP-Timestamp"]
    mac = hmac.new(
        secret.encode(), timestamp.encode() + b"." + request.content, hashlib.sha256
    ).hexdigest()
    assert request.headers["X-MBP-Signature"] == f"sha256={mac}"


def test_create_shows_the_secret_once(auth_client, receiver):
    created = create(auth_client)
    assert created["secret"].startswith("whsec_")
    listed = auth_client.get("/api/webhooks").json()
    assert [w["name"] for w in listed] == ["erp"]
    assert created["secret"] not in str(listed)


def test_unknown_events_and_bad_urls(auth_client):
    body = {"name": "x", "url": "https://a.example.com", "events": ["nope"]}
    response = auth_client.post("/api/webhooks", json=body)
    assert response.status_code == 422
    assert response.json()["fields"] == {"events": "unknown"}
    body = {"name": "x", "url": "ftp://a.example.com", "events": ["*"]}
    assert auth_client.post("/api/webhooks", json=body).status_code == 422


def test_ping_is_signed(auth_client, receiver):
    created = create(auth_client)
    hook_id = created["webhook"]["id"]
    delivery = auth_client.post(f"/api/webhooks/{hook_id}/test").json()
    assert (delivery["status"], delivery["response_status"], delivery["attempts"]) == (
        "sent",
        200,
        1,
    )
    [request] = receiver.requests
    assert str(request.url) == "https://hooks.example.com/mbp"
    assert request.headers["X-MBP-Event"] == "ping"
    assert request.headers["X-MBP-Delivery"] == delivery["uuid"]
    check_signature(created["secret"], request)
    body = json.loads(request.content)
    assert body["event"] == "ping" and body["id"] == delivery["uuid"]
    hook = auth_client.get(f"/api/webhooks/{hook_id}").json()
    assert (hook["last_status"], hook["failures"]) == ("HTTP 200", 0)


def test_rotating_the_secret(auth_client, receiver):
    created = create(auth_client)
    hook_id = created["webhook"]["id"]
    rotated = auth_client.post(f"/api/webhooks/{hook_id}/rotate-secret").json()
    assert rotated["secret"] != created["secret"]
    auth_client.post(f"/api/webhooks/{hook_id}/test")
    check_signature(rotated["secret"], receiver.requests[-1])


def test_events_are_delivered_with_retries(app, auth_client, receiver):
    created = create(auth_client, events=["backup_failed"])
    create(auth_client, name="other", events=["deploy_succeeded"])
    receiver.statuses = [500, 503, 200]
    event = Event("backup_failed", "backup_failed:1:shop", {"instance": "prod", "db": "shop"})
    ids = app.state.webhooks.dispatch(event)
    assert len(ids) == 1
    assert len(receiver.requests) == 3
    # A retry keeps the delivery's ID.
    assert len({r.headers["X-MBP-Delivery"] for r in receiver.requests}) == 1
    check_signature(created["secret"], receiver.requests[-1])
    body = json.loads(receiver.requests[-1].content)
    assert body["event"] == "backup_failed"
    assert body["params"] == {"instance": "prod", "db": "shop"}
    assert body["severity"] == "error" and "shop" in body["message"]
    [delivery] = auth_client.get(f"/api/webhooks/{created['webhook']['id']}/deliveries").json()
    assert (delivery["status"], delivery["attempts"]) == ("sent", 3)


def test_failed_delivery_and_redelivery(app, auth_client, receiver):
    created = create(auth_client)
    hook_id = created["webhook"]["id"]
    receiver.statuses = [500]
    app.state.webhooks.dispatch(Event("deploy_failed", "deploy_failed:1", {"project": "shop"}))
    assert len(receiver.requests) == 3
    [failed] = auth_client.get(f"/api/webhooks/{hook_id}/deliveries").json()
    assert (failed["status"], failed["response_status"], failed["detail"]) == (
        "failed",
        500,
        "nope",
    )
    hook = auth_client.get(f"/api/webhooks/{hook_id}").json()
    assert (hook["failures"], hook["last_status"]) == (1, "HTTP 500")

    receiver.statuses = [200]
    again = auth_client.post(f"/api/webhooks/deliveries/{failed['id']}/redeliver").json()
    assert again["status"] == "sent" and again["uuid"] != failed["uuid"]
    assert again["payload"]["id"] == again["uuid"]
    assert again["payload"]["params"] == {"project": "shop"}
    only_failed = auth_client.get(
        f"/api/webhooks/{hook_id}/deliveries", params={"status": "failed"}
    ).json()
    assert [d["id"] for d in only_failed] == [failed["id"]]
    assert auth_client.get(f"/api/webhooks/{hook_id}").json()["failures"] == 0


def test_unreachable_address(app, auth_client):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    app.state.webhooks = WebhookDispatcher(
        get_sessionmaker(), background=False, transport=httpx.MockTransport(refuse)
    )
    hook_id = create(auth_client)["webhook"]["id"]
    delivery = auth_client.post(f"/api/webhooks/{hook_id}/test").json()
    assert delivery["status"] == "failed"
    assert delivery["detail"].startswith("ConnectError")


def test_disabled_webhooks_get_nothing(app, auth_client, receiver):
    hook_id = create(auth_client)["webhook"]["id"]
    auth_client.patch(f"/api/webhooks/{hook_id}", json={"enabled": False})
    assert app.state.webhooks.dispatch(Event("backup_failed", "s")) == []
    assert receiver.requests == []


def test_update_and_delete(auth_client, receiver):
    hook_id = create(auth_client)["webhook"]["id"]
    out = auth_client.patch(
        f"/api/webhooks/{hook_id}", json={"events": ["site_down", "backup_failed"]}
    ).json()
    # In the canonical order, whatever order they were given in.
    assert out["events"] == ["backup_failed", "site_down"]
    assert out["name"] == "erp"
    assert auth_client.delete(f"/api/webhooks/{hook_id}").status_code == 204
    assert auth_client.get(f"/api/webhooks/{hook_id}").status_code == 404


def test_managed_through_the_api_too(client, db, admin, receiver):
    _, secret = make_key(db, admin, scopes=["webhooks:write"])
    body = {"name": "self", "url": "https://me.example.com/hook", "events": ["*"]}
    response = client.post("/api/v1/webhooks", json=body, headers=bearer(secret))
    assert response.status_code == 201
    assert "secret" in response.json()
    events = client.get("/api/v1/webhooks/-/events", headers=bearer(secret)).json()
    assert events[0] == "*" and "ping" in events
    _, reader = make_key(db, admin, scopes=["webhooks:read"])
    response = client.post("/api/v1/webhooks", json=body, headers=bearer(reader))
    assert response.json() == {"code": "insufficient_scope", "detail": "webhooks:write"}


# --- the notifier's events ---


class Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    def dispatch(self, event, created_at=None):
        self.events.append(event.type)
        return []


def test_notifier_sends_events_to_webhooks_whatever_the_rules(auth_client, db):
    settings = auth_client.get("/api/notifications/settings").json()
    rules = settings["rules"]
    rules["backup_failed"] = {"enabled": False, "channels": []}
    body = {k: settings[k] for k in settings if k not in ("events", "has_webhook_secret")}
    response = auth_client.put("/api/notifications/settings", json={**body, "rules": rules})
    assert response.status_code == 200, response.text

    notifier = Notifier(get_sessionmaker(), background=False)
    notifier.webhooks = Recorder()
    assert notifier.emit(Event("backup_failed", "backup_failed:1:a")) is None
    assert notifier.webhooks.events == ["backup_failed"]
    assert db.query(NotificationLog).count() == 0


def test_notifier_keeps_the_cooldown_for_webhooks():
    notifier = Notifier(get_sessionmaker(), background=False)
    notifier.webhooks = Recorder()
    notifier.emit(Event("site_down", "site_down:1"))
    notifier.emit(Event("site_down", "site_down:1"))
    assert notifier.webhooks.events == ["site_down"]
    # The test button is not an event for webhooks.
    notifier.emit(Event("test", "test"), channels=[])
    assert notifier.webhooks.events == ["site_down"]


def test_deliveries_are_pruned(app, auth_client, receiver, monkeypatch):
    from mbp.apiaccess import webhooks

    monkeypatch.setattr(webhooks, "KEEP_DELIVERIES", 3)
    hook_id = create(auth_client)["webhook"]["id"]
    for _ in range(5):
        auth_client.post(f"/api/webhooks/{hook_id}/test")
    with get_sessionmaker()() as db:
        assert db.query(ApiWebhookDelivery).count() == 3
