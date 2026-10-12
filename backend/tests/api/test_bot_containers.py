"""The bot's containers menu: viewing, logs, and actions confirmed with a TOTP code."""

import pytest

from mbp.models import AdminAccount, ContainerAction
from tests.api.test_bots import buttons, press, say
from tests.api.test_two_factor import code_for, enable

SHOP = {"com.docker.compose.project": "shop", "com.docker.compose.service": "web"}


@pytest.fixture
def bot(bale_bot, containers_client, docker):
    docker.add("shop-web-1", labels=SHOP, logs=[("stdout", "GET / 200"), ("stderr", "warn: slow")])
    docker.add("worker", state="exited", exit_code=1)
    docker.add("panel-backend", labels={"mbp.role": "panel"})
    return bale_bot


def open_container(fake, name):
    screen = press(fake, "cl:0")
    data = next(b["callback_data"] for b in buttons(screen) if name in b["text"])
    return data, press(fake, data)


def button_data(screen, text):
    return next(b["callback_data"] for b in buttons(screen) if text in b["text"])


def set_settings(client, **values):
    body = client.get("/api/containers/-/settings").json()
    body.update(values)
    assert client.put("/api/containers/-/settings", json=body).status_code == 200


def test_list_and_details(bot, docker):
    menu = say(bot, "/start")
    assert "cl:0" in [b["callback_data"] for b in buttons(menu)]
    screen = press(bot, "cl:0")
    assert "2" in screen["text"] or "۲" in screen["text"]  # running count
    names = [b["text"] for b in buttons(screen)]
    # Problems first.
    assert names[0].startswith("🔴") and "worker" in names[0]
    _, details = open_container(bot, "shop-web-1")
    text = details["text"]
    assert "shop-web-1" in text and "nginx:1.27" in text and "shop / web" in text
    assert "8080→80/tcp" in text
    assert "Very-Secret-42" not in text
    labels = [b["text"] for b in buttons(details)]
    assert any("ری‌استارت" in label for label in labels)
    server = press(bot, "cs")
    assert "Docker 27.3.1" in server["text"]


def test_panel_containers_have_no_controls(bot):
    _, details = open_container(bot, "panel-backend")
    assert "🔒" in details["text"]
    assert not [b for b in buttons(details) if b["callback_data"].startswith("ca:")]


def test_logs_are_off_until_enabled(bot, containers_client):
    data, details = open_container(bot, "shop-web-1")
    logs = press(bot, button_data(details, "لاگ"))
    assert "GET / 200" not in logs["text"]
    set_settings(containers_client, bot_logs=True)
    logs = press(bot, button_data(details, "لاگ"))
    assert "GET / 200" in logs["text"] and "! warn: slow" in logs["text"]


def test_actions_need_two_step_verification(bot, docker, db):
    _, details = open_container(bot, "shop-web-1")
    screen = press(bot, button_data(details, "ری‌استارت"))
    assert "ورود دو مرحله‌ای" in screen["text"]
    assert docker.containers["shop-web-1"].state == "running"
    assert db.query(ContainerAction).count() == 0


def test_restart_confirmed_with_a_code(bot, containers_client, docker, db):
    secret, _ = enable(containers_client)
    _, details = open_container(bot, "shop-web-1")
    prompt = press(bot, button_data(details, "توقف"))
    assert "Google Authenticator" in prompt["text"]
    wrong = say(bot, "000000")
    assert "اشتباه" in wrong["text"]
    assert docker.containers["shop-web-1"].state == "running"
    done = say(bot, code_for(secret, 1))
    assert "✅" in done["text"]
    assert docker.containers["shop-web-1"].state == "exited"
    entry = db.query(ContainerAction).one()
    assert (entry.action, entry.result, entry.source) == ("stop", "ok", "bale")
    assert entry.actor == "Ops (admin)"
    # The code is spent: the same code cannot be used again (here or in the panel).
    db.expire_all()
    assert db.query(AdminAccount).one().totp_last_step is not None


def test_other_text_cancels_and_codes_are_single_use(bot, containers_client, docker, db):
    secret, _ = enable(containers_client)
    _, details = open_container(bot, "shop-web-1")
    press(bot, button_data(details, "توقف"))
    menu = say(bot, "hello")
    assert "cl:0" in [b["callback_data"] for b in buttons(menu)]
    # The request is gone: a code now does nothing but show the menu.
    say(bot, code_for(secret, 1))
    assert docker.containers["shop-web-1"].state == "running"


def test_too_many_wrong_codes_block_actions(bot, containers_client, docker):
    enable(containers_client)
    _, details = open_container(bot, "shop-web-1")
    stop = button_data(details, "توقف")
    press(bot, stop)
    for _ in range(3):
        last = say(bot, "111111")
    assert "زمان تأیید" in last["text"] or "بسته شد" in last["text"]
    press(bot, stop)
    for _ in range(2):
        last = say(bot, "222222")
    assert "۱۵ دقیقه" in last["text"]
    assert "۱۵ دقیقه" in press(bot, stop)["text"]
    assert docker.containers["shop-web-1"].state == "running"


def test_read_only_and_locked(bot, containers_client):
    enable(containers_client)
    data, details = open_container(bot, "shop-web-1")
    stop = button_data(details, "توقف")
    set_settings(containers_client, locked=["shop-*"])
    assert "قفل" in press(bot, stop)["text"]
    set_settings(containers_client, locked=[], read_only=True)
    assert "فقط‌خواندنی" in press(bot, stop)["text"]
    details = press(bot, data)
    assert not [b for b in buttons(details) if b["callback_data"].startswith("ca:")]


def test_without_the_agent(bale_bot):
    screen = press(bale_bot, "cl:0")
    assert "agent" in screen["text"]


def test_several_servers(bot, containers_client, remote, docker, db):
    secret, _ = enable(containers_client)
    servers = press(bot, "cl:0")
    choices = [b["callback_data"] for b in buttons(servers) if b["callback_data"].startswith("cl:")]
    assert len(choices) == 2
    edge = button_data(servers, "edge")
    assert edge == f"cl:0:{remote['id']}"
    screen = press(bot, edge)
    assert "edge" in screen["text"]
    data = next(b["callback_data"] for b in buttons(screen) if "shop-web-1" in b["text"])
    details = press(bot, data)
    assert f"cl:0:{remote['id']}" in [b["callback_data"] for b in buttons(details)]
    press(bot, button_data(details, "ری‌استارت"))
    done = say(bot, code_for(secret, 1))
    assert "✅" in done["text"]
    entry = db.query(ContainerAction).one()
    assert (entry.server_id, entry.server_name, entry.action) == (remote["id"], "edge", "restart")
    status = press(bot, f"cs:{remote['id']}")
    assert "Docker" in status["text"]
