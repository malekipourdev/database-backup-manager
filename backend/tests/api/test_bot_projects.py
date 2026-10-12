"""The bot's projects menu: viewing and deploys confirmed with a TOTP code."""

import pytest

from mbp.models import Deployment
from tests.api.test_bots import buttons, press, say
from tests.api.test_projects import body, wait_deploy
from tests.api.test_two_factor import code_for, enable
from tests.conftest import wait_until


@pytest.fixture
def bot(bale_bot, containers_client):
    return bale_bot


def make_project(client, **overrides):
    response = client.post("/api/projects", json=body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def sent_texts(fake):
    with fake.lock:
        return [b.get("text", "") for m, b in fake.sent if m == "sendMessage"]


def test_list_and_view(bot, containers_client):
    menu = say(bot, "/start")
    assert "pl:0" in [b["callback_data"] for b in buttons(menu)]
    assert "هنوز پروژه‌ای" in press(bot, "pl:0")["text"]
    project = make_project(containers_client)
    screen = press(bot, "pl:0")
    assert [b["text"] for b in buttons(screen)][0] == "⚪️ shop"
    view = press(bot, f"p:{project['id']}")
    assert "github.com/acme/shop.git" in view["text"] and "main" in view["text"]
    assert "هنوز دیپلوی نشده" in view["text"]
    assert "ghp_" not in view["text"]


def test_deploy_needs_two_step_verification(bot, containers_client, db):
    project = make_project(containers_client)
    screen = press(bot, f"pd:{project['id']}")
    assert "ورود دو مرحله‌ای" in screen["text"]
    assert db.query(Deployment).count() == 0


def test_deploy_confirmed_with_a_code(bot, containers_client, db):
    secret, _ = enable(containers_client)
    project = make_project(containers_client)
    prompt = press(bot, f"pd:{project['id']}")
    assert "Google Authenticator" in prompt["text"]
    assert "اشتباه" in say(bot, "000000")["text"]
    assert db.query(Deployment).count() == 0
    say(bot, code_for(secret, 1))
    # "Started", then (quickly, with the scripted agent) the result.
    wait_until(lambda: any("شروع شد" in t for t in sent_texts(bot)), message="started")
    deployment = wait_until(lambda: db.query(Deployment).first(), message="deployment")
    result = wait_deploy(containers_client, deployment.id)
    assert result["status"] == "success"
    assert (result["trigger"], result["actor"]) == ("bale", "Ops (admin)")
    # The result is reported in the chat that asked.
    wait_until(lambda: any("✅" in t and "shop" in t for t in sent_texts(bot)), message="result")
    view = press(bot, f"p:{project['id']}")
    assert "✅" in view["text"] and "aaaaaaaa" in view["text"]
    history = press(bot, f"ph:{project['id']}")
    assert "aaaaaaaa" in history["text"] and "Ops (admin)" in history["text"]


def test_failed_deploy_is_reported(bot, containers_client, agent_commands, db):
    agent_commands.fail["compose up"] = 1
    secret, _ = enable(containers_client)
    project = make_project(containers_client)
    press(bot, f"pd:{project['id']}")
    say(bot, code_for(secret, 1))
    wait_until(
        lambda: any("❌" in t and "اجرای سرویس‌ها" in t for t in sent_texts(bot)),
        message="failure message",
    )


def test_cancel(bot, containers_client, db):
    enable(containers_client)
    project = make_project(containers_client)
    press(bot, f"pd:{project['id']}")
    screen = press(bot, f"pdx:{project['id']}")
    assert "لغو" in screen["text"]
    assert db.query(Deployment).count() == 0
