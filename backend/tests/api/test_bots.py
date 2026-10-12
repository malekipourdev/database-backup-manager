"""Bots: settings, admins, link codes, and the bot itself over a fake Bot API (real HTTP)."""

import json

import pytest

from mbp.db import get_sessionmaker
from mbp.models import BotLinkCode
from tests.conftest import (
    BACKUP_ROOT,
    BOT_ADMIN_ID,
    STRANGER_ID,
    create_instance,
    wait_for_run,
    wait_until,
)
from tests.fakes.fake_bot_api import TOKEN


def buttons(body: dict) -> list[dict]:
    markup = body.get("reply_markup") or {}
    if isinstance(markup, str):
        markup = json.loads(markup)
    return [b for row in markup.get("inline_keyboard", []) for b in row]


def last_screen(fake, after: int = 0):
    """The newest message the bot sent or edited (text, buttons)."""

    def find():
        with fake.lock:
            screens = [b for m, b in fake.sent if m in ("sendMessage", "editMessageText")]
        return screens[after:] or None

    screens = wait_until(find, message="a bot message")
    return screens[-1]


def count(fake) -> int:
    with fake.lock:
        return len([1 for m, _ in fake.sent if m in ("sendMessage", "editMessageText")])


def press(fake, data: str):
    before = count(fake)
    fake.push_callback(BOT_ADMIN_ID, data)
    wait_until(lambda: count(fake) > before, message=f"answer to {data}")
    screen = last_screen(fake, before)
    for b in buttons(screen):
        assert len(b["callback_data"].encode()) <= 64, b
    return screen


def say(fake, text: str, user_id: int = BOT_ADMIN_ID, messages: int = 1):
    """Send a message; returns the last of the `messages` answers it is expected to get."""
    before = count(fake)
    fake.push_message(user_id, text)
    wait_until(lambda: count(fake) >= before + messages, message=f"answer to {text}")
    return last_screen(fake, before)


# --- settings and admins API ---


def test_settings_never_return_the_token(auth_client):
    bots = auth_client.get("/api/bots").json()
    assert [b["platform"] for b in bots] == ["bale", "telegram"]
    assert all(b["has_token"] is False and b["enabled"] is False for b in bots)

    assert auth_client.put("/api/bots/bale", json={"enabled": True}).status_code == 422
    saved = auth_client.put("/api/bots/bale", json={"enabled": False, "token": TOKEN}).json()
    assert saved["has_token"] is True
    assert TOKEN not in json.dumps(saved)
    assert TOKEN not in auth_client.get("/api/bots").text
    cleared = auth_client.delete("/api/bots/bale/token").json()
    assert cleared["has_token"] is False
    assert auth_client.put("/api/bots/whatsapp", json={}).status_code == 404


@pytest.mark.parametrize(
    "proxy",
    ["socks5://user:pass@proxy:1080", "ftp://proxy:21", "proxy:8080"],
)
def test_proxy_validation(auth_client, proxy):
    response = auth_client.put("/api/bots/telegram", json={"proxy_url": proxy})
    assert response.status_code == 422
    ok = auth_client.put("/api/bots/telegram", json={"proxy_url": "socks5h://127.0.0.1:1080"})
    assert ok.status_code == 200


def test_bot_test_endpoint(auth_client, fake_bot_server):
    ok = auth_client.post(
        "/api/bots/bale/test", json={"token": TOKEN, "api_base_url": fake_bot_server.url}
    ).json()
    assert ok == {"ok": True, "username": "mbp_test_bot", "error_code": None, "error_detail": None}
    bad = auth_client.post(
        "/api/bots/bale/test", json={"token": "1:wrong", "api_base_url": fake_bot_server.url}
    ).json()
    assert bad["ok"] is False and bad["error_code"] == "unauthorized"
    assert "1:wrong" not in json.dumps(bad)
    down = auth_client.post(
        "/api/bots/bale/test", json={"token": TOKEN, "api_base_url": "http://127.0.0.1:9"}
    ).json()
    assert down["error_code"] == "unreachable"
    assert TOKEN not in json.dumps(down)


def test_admin_crud(auth_client):
    body = {"platform": "bale", "user_id": 42, "display_name": "Sara"}
    created = auth_client.post("/api/bot-admins", json=body)
    assert created.status_code == 201
    admin = created.json()
    assert admin["notify_level"] == "warning" and admin["language"] == "fa"
    assert auth_client.post("/api/bot-admins", json=body).status_code == 409
    # The same person may also be registered on the other platform.
    other = auth_client.post("/api/bot-admins", json={**body, "platform": "telegram"})
    assert other.status_code == 201
    updated = auth_client.patch(
        f"/api/bot-admins/{admin['id']}", json={"notify_level": "error", "enabled": False}
    ).json()
    assert (updated["notify_level"], updated["enabled"]) == ("error", False)
    assert auth_client.delete(f"/api/bot-admins/{admin['id']}").status_code == 204
    assert len(auth_client.get("/api/bot-admins").json()) == 1


def test_link_code_is_stored_hashed(auth_client):
    response = auth_client.post("/api/bots/telegram/link-codes", json={"display_name": "Ali"})
    assert response.status_code == 201
    code = response.json()["code"]
    assert len(code) == 8
    with get_sessionmaker()() as db:
        stored = db.query(BotLinkCode).one()
        assert code not in stored.code_hash


# --- the bot ---


def test_strangers_only_get_their_id(bale_bot):
    screen = say(bale_bot, "/start", user_id=STRANGER_ID)
    assert str(STRANGER_ID).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) in screen["text"]
    assert buttons(screen) == []
    # A stranger's button press is refused without any data.
    bale_bot.push_callback(STRANGER_ID, "st")
    wait_until(lambda: bale_bot.calls("answerCallbackQuery"), message="refusal")
    assert all(b.get("chat_id") != STRANGER_ID for b in bale_bot.calls("editMessageText"))


def test_group_chats_are_ignored(bale_bot):
    bale_bot.push_message(BOT_ADMIN_ID, "/start", chat_type="group")
    say(bale_bot, "/start")  # the next private message is answered...
    texts = [b["text"] for b in bale_bot.calls("sendMessage")]
    assert len(texts) == 1  # ...and the group message never was


def test_link_code_registers_the_sender(auth_client, bale_bot):
    code = auth_client.post("/api/bots/bale/link-codes", json={"display_name": "Reza"}).json()[
        "code"
    ]
    # Two answers: "linked", then the menu.
    screen = say(bale_bot, f"/start {code}", user_id=555, messages=2)
    assert "منو" in screen["text"] or "MySQL" in screen["text"]
    admins = {a["user_id"]: a for a in auth_client.get("/api/bot-admins").json()}
    assert admins[555]["display_name"] == "Reza"
    # Codes work once.
    again = say(bale_bot, code, user_id=556)
    assert "نامعتبر" in again["text"]
    assert 556 not in {a["user_id"] for a in auth_client.get("/api/bot-admins").json()}


def test_menu_and_status(bale_bot, auth_client):
    create_instance(auth_client)
    screen = say(bale_bot, "/start")
    data = {b["callback_data"] for b in buttons(screen)}
    assert {"st", "il:0", "rl:0:0", "sl:0", "rt", "ns"} <= data
    status = press(bale_bot, "st")
    assert "سرورها: ۱" in status["text"]


def test_disabled_admin_is_refused(bale_bot, auth_client):
    admin = auth_client.get("/api/bot-admins").json()[0]
    auth_client.patch(f"/api/bot-admins/{admin['id']}", json={"enabled": False})
    screen = say(bale_bot, "/start")
    assert buttons(screen) == []


def test_backup_all_from_the_bot(bale_bot, auth_client, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop", "ok_blog"))
    press(bale_bot, "il:0")
    detail = press(bale_bot, f"i:{instance_id}")
    assert "ok_blog" in detail["text"]
    confirm = press(bale_bot, f"ba:{instance_id}")
    assert {b["callback_data"] for b in buttons(confirm)} == {
        f"bac:{instance_id}",
        f"i:{instance_id}",
    }
    # Nothing starts before confirming.
    assert auth_client.get("/api/backups/runs").json()["total"] == 0
    press(bale_bot, f"bac:{instance_id}")
    runs = auth_client.get("/api/backups/runs").json()["items"]
    assert sorted(r["database_name"] for r in runs) == ["ok_blog", "ok_shop"]
    for run in runs:
        assert wait_for_run(auth_client, run["id"])["status"] == "success"


def test_back_up_one_database_by_button(bale_bot, auth_client, probe_ok, monkeypatch):
    from mbp.services import mysql_probe

    long_name = "ok_" + "ف" * 60  # 123 bytes: does not fit in callback data, uses a token
    monkeypatch.setattr(
        mysql_probe,
        "list_databases",
        lambda params, timeout=None: mysql_probe.ListResult(ok=True, names=["sys", long_name]),
    )
    instance_id = create_instance(auth_client)
    screen = press(bale_bot, f"dl:{instance_id}:0")
    choices = [b for b in buttons(screen) if b["callback_data"].startswith("bo:")]
    assert [b["text"] for b in choices] == [long_name]  # system schemas are not offered
    press(bale_bot, choices[0]["callback_data"])
    run = auth_client.get("/api/backups/runs").json()["items"][0]
    assert run["database_name"] == long_name
    wait_for_run(auth_client, run["id"])


def test_run_detail_file_and_delete(bale_bot, auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_shop"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    detail = press(bale_bot, f"r:{run_id}")
    assert "ok_shop" in detail["text"]
    assert f"rf:{run_id}" in {b["callback_data"] for b in buttons(detail)}

    # Sending files is off by default: the database's data stays off the messenger.
    refused = press(bale_bot, f"rf:{run_id}")
    assert "غیرفعال" in refused["text"]
    assert bale_bot.calls("sendDocument") == []

    auth_client.put(
        "/api/bots/bale",
        json={
            "enabled": True,
            "api_base_url": bale_bot.url,
            "allow_file_download": True,
            "max_file_mb": 20,
        },
    )
    wait_until(lambda: auth_client.get("/api/bots").json()[0]["running"], message="bot restart")
    bale_bot.push_callback(BOT_ADMIN_ID, f"rf:{run_id}")
    document = wait_until(lambda: bale_bot.calls("sendDocument"), message="document")[0]
    assert document["document"]["filename"].endswith(".sql.gz")
    assert document["document"]["size"] > 0
    assert int(document["chat_id"]) == BOT_ADMIN_ID

    confirm = press(bale_bot, f"rd:{run_id}")
    # No remote copy: only the local delete is offered.
    assert {b["callback_data"] for b in buttons(confirm)} == {f"rdc:{run_id}:0", f"r:{run_id}"}
    press(bale_bot, f"rdc:{run_id}:0")
    assert auth_client.get(f"/api/backups/runs/{run_id}").status_code == 404
    assert not list(BACKUP_ROOT.rglob("*.sql.gz"))


def test_schedules_from_the_bot(bale_bot, auth_client, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop",))
    schedule = auth_client.post(
        f"/api/instances/{instance_id}/schedules",
        json={"name": "Nightly", "cron": "0 2 * * *", "timezone": "UTC", "scope": "all"},
    ).json()
    listing = press(bale_bot, "sl:0")
    assert f"s:{schedule['id']}" in {b["callback_data"] for b in buttons(listing)}
    toggled = press(bale_bot, f"se:{schedule['id']}")
    assert "غیرفعال" in toggled["text"]
    assert auth_client.get(f"/api/schedules/{schedule['id']}").json()["enabled"] is False
    ran = press(bale_bot, f"sr:{schedule['id']}")
    assert "شروع شد" in ran["text"]
    run = auth_client.get("/api/backups/runs").json()["items"][0]
    assert run["trigger"] == "schedule"
    wait_for_run(auth_client, run["id"])


def test_retention_preview_and_apply(bale_bot, auth_client):
    from tests.api.test_retention import seed_success

    instance_id = create_instance(auth_client)
    seed_success(instance_id, "shop", 0)
    _, old = seed_success(instance_id, "shop", 5)
    auth_client.put("/api/retention", json={"local_keep_last": 1})
    preview = press(bale_bot, "rtp")
    assert "shop_5" in preview["text"]
    assert old.exists()
    press(bale_bot, "rta")
    assert not old.exists()


def test_settings_level_and_language(bale_bot, auth_client):
    screen = press(bale_bot, "ns")
    assert "nl:error" in {b["callback_data"] for b in buttons(screen)}
    press(bale_bot, "nl:error")
    english = press(bale_bot, "lg")
    assert "Notification level" in english["text"]
    admin = auth_client.get("/api/bot-admins").json()[0]
    assert (admin["notify_level"], admin["language"]) == ("error", "en")


def test_unknown_or_stale_buttons(bale_bot):
    screen = press(bale_bot, "bo:doesnotexist")
    assert "منقضی" in screen["text"]
    screen = press(bale_bot, "zz:1")
    assert "منقضی" in screen["text"]


def test_missing_objects_give_an_error_not_a_crash(bale_bot):
    screen = press(bale_bot, "i:9999")
    assert "instance_not_found" in screen["text"] or "خطا" in screen["text"]


def test_token_never_logged(bale_bot, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    say(bale_bot, "/start")
    assert TOKEN not in caplog.text


def test_strangers_typing_words_get_their_id(bale_bot):
    screen = say(bale_bot, "hello there", user_id=STRANGER_ID)
    assert "شناسه" in screen["text"]
    screen = say(bale_bot, "ZZZZ9999", user_id=STRANGER_ID)  # looks like a code, is not one
    assert "نامعتبر" in screen["text"]


def test_bot_never_offers_deleting_a_protected_remote_copy(bale_bot, auth_client, s3, probe_ok):
    from tests.api.test_remote_storage import age_remote, configure, objects

    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_shop"}
    ).json()["created"][0]["id"]
    from tests.conftest import wait_for_remote

    wait_for_run(auth_client, run_id)
    wait_for_remote(auth_client, run_id)
    confirm = press(bale_bot, f"rd:{run_id}")
    assert {b["callback_data"] for b in buttons(confirm)} == {f"rdc:{run_id}:0", f"r:{run_id}"}
    assert "۷ روز" in confirm["text"]
    # Even a hand-made callback can't delete it.
    refused = press(bale_bot, f"rdc:{run_id}:1")
    assert "remote_protected" in refused["text"]
    assert len(objects(s3)) == 1

    press(bale_bot, f"rdc:{run_id}:0")
    assert len(objects(s3)) == 1  # kept
    age_remote(run_id, 8)
    confirm = press(bale_bot, f"rd:{run_id}")
    assert f"rdc:{run_id}:1" in {b["callback_data"] for b in buttons(confirm)}
    press(bale_bot, f"rdc:{run_id}:1")
    assert objects(s3) == []
