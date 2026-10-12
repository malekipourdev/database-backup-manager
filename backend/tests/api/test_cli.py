"""Server-side admin commands: list admins, reset a forgotten password."""

import re

from mbp.models import AuthSession, LoginAttempt
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def login(client, password):
    return client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": password})


def test_list_admins(admin, capsys):
    from mbp.cli import main

    assert main(["list-admins"]) == 0
    assert capsys.readouterr().out.strip() == f"{ADMIN_USERNAME}\tpassword only"


def test_reset_password_generated(auth_client, db, capsys):
    from mbp.cli import main

    # A lockout from failed attempts and an open session.
    for _ in range(6):
        login(auth_client, "wrong")
    assert db.query(LoginAttempt).count() == 1
    assert db.query(AuthSession).count() == 1

    assert main(["reset-password", ADMIN_USERNAME, "--generate"]) == 0
    out = capsys.readouterr().out
    new = re.search(r"New password: (\S+)", out).group(1)
    db.expire_all()
    assert db.query(AuthSession).count() == 0
    assert db.query(LoginAttempt).count() == 0
    auth_client.cookies.clear()
    assert login(auth_client, ADMIN_PASSWORD).status_code == 401
    assert login(auth_client, new).status_code == 200


def test_reset_password_prompted(client, admin, monkeypatch, capsys):
    from mbp import cli

    answers = iter(["Brand-New-Pass-1", "Brand-New-Pass-1"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["reset-password", ADMIN_USERNAME]) == 0
    assert "Brand-New-Pass-1" not in capsys.readouterr().out
    assert login(client, "Brand-New-Pass-1").status_code == 200


def test_reset_password_rejections(client, admin, monkeypatch):
    from mbp import cli

    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "short")
    assert cli.main(["reset-password", ADMIN_USERNAME]) == 1
    answers = iter(["Long-Enough-Pass-1", "Different-Pass-22"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["reset-password", ADMIN_USERNAME]) == 1
    assert cli.main(["reset-password", "nobody", "--generate"]) == 1
    assert login(client, ADMIN_PASSWORD).status_code == 200
