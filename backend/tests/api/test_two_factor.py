"""Two-factor authentication (TOTP): setup, sign-in, recovery codes, replay and lockout."""

import logging
import time

import pyotp
import pytest

from mbp.security import totp
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def code_for(secret: str, offset_steps: int = 0) -> str:
    return pyotp.TOTP(secret).at(time.time() + offset_steps * 30)


def login(client, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": password})


def enable(client) -> tuple[str, list[str]]:
    """Turn on 2FA for the signed-in admin; returns (secret, recovery codes)."""
    setup = client.post("/api/auth/2fa/setup", json={"password": ADMIN_PASSWORD})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    response = client.post("/api/auth/2fa/enable", json={"code": code_for(secret)})
    assert response.status_code == 200, response.text
    return secret, response.json()["recovery_codes"]


@pytest.fixture
def two_factor(auth_client):
    secret, codes = enable(auth_client)
    auth_client.cookies.clear()
    return secret, codes


# --- TOTP primitives ---


def test_totp_window_and_replay():
    secret = totp.new_secret()
    now = time.time()
    current = int(now // 30)
    assert totp.verify(secret, pyotp.TOTP(secret).at(now), None, now) == current
    # Codes from one step before or after are accepted (clock drift) ...
    assert totp.verify(secret, pyotp.TOTP(secret).at(now - 30), None, now) == current - 1
    # ... but not from further away, and never a step that was already used.
    assert totp.verify(secret, pyotp.TOTP(secret).at(now - 90), None, now) is None
    assert totp.verify(secret, pyotp.TOTP(secret).at(now), current, now) is None
    assert totp.verify(secret, "12345", None, now) is None
    assert totp.verify(secret, "abcdef", None, now) is None


def test_recovery_codes_are_single_use():
    codes = totp.new_recovery_codes()
    assert len(codes) == 8 and len(set(codes)) == 8
    hashes = [totp.hash_recovery_code(c) for c in codes]
    assert codes[0] not in "".join(hashes)
    remaining = totp.use_recovery_code(hashes, codes[0].upper().replace("-", " "))
    assert remaining is not None and len(remaining) == 7
    assert totp.use_recovery_code(remaining, codes[0]) is None


def test_qr_code_is_inline_svg():
    uri = totp.provisioning_uri(totp.new_secret(), "admin")
    assert uri.startswith("otpauth://totp/MySQL%20Backup%20Panel:admin?secret=")
    assert totp.qr_svg_data_uri(uri).startswith("data:image/svg+xml")


# --- setup ---


def test_setup_needs_the_password(auth_client):
    response = auth_client.post("/api/auth/2fa/setup", json={"password": "wrong"})
    assert response.status_code == 403
    assert response.json()["code"] == "wrong_password"
    assert auth_client.get("/api/auth/2fa").json() == {"enabled": False, "recovery_codes_left": 0}


def test_enable_needs_a_valid_code(auth_client):
    secret = auth_client.post("/api/auth/2fa/setup", json={"password": ADMIN_PASSWORD}).json()[
        "secret"
    ]
    bad = auth_client.post("/api/auth/2fa/enable", json={"code": "000000"})
    assert bad.status_code == 422
    assert auth_client.get("/api/auth/me").json()["two_factor_enabled"] is False
    ok = auth_client.post("/api/auth/2fa/enable", json={"code": code_for(secret)})
    assert ok.status_code == 200
    assert len(ok.json()["recovery_codes"]) == 8
    assert auth_client.get("/api/auth/2fa").json() == {"enabled": True, "recovery_codes_left": 8}
    assert auth_client.get("/api/auth/me").json()["two_factor_enabled"] is True
    # The current session keeps working.
    assert auth_client.get("/api/instances").status_code == 200


def test_enabling_signs_out_other_sessions(auth_client, admin, db, app):
    from fastapi.testclient import TestClient

    from mbp.repositories.session_repository import SessionRepository
    from mbp.security.sessions import COOKIE_NAME

    other_token = SessionRepository(db).create(admin.id)
    db.commit()
    enable(auth_client)
    with TestClient(app, headers={"X-Requested-With": "mbp"}) as other:
        other.cookies.set(COOKIE_NAME, other_token)
        assert other.get("/api/auth/me").status_code == 401
    assert auth_client.get("/api/auth/me").status_code == 200


# --- sign-in ---


def test_password_alone_no_longer_signs_in(client, two_factor):
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["two_factor_required"] is True and body["challenge"]
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401


def test_sign_in_with_code(client, two_factor):
    secret, _ = two_factor
    challenge = login(client).json()["challenge"]
    response = client.post(
        "/api/auth/login/2fa", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert response.status_code == 200
    assert response.json()["two_factor_required"] is False
    assert client.get("/api/auth/me").json()["username"] == ADMIN_USERNAME

    # The same code can't be used again (replay), even with a fresh challenge.
    client.cookies.clear()
    challenge = login(client).json()["challenge"]
    replay = client.post(
        "/api/auth/login/2fa", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "invalid_code"


def test_sign_in_with_recovery_code_once(client, two_factor):
    _, codes = two_factor
    for expected in (200, 401):
        client.cookies.clear()
        challenge = login(client).json()["challenge"]
        response = client.post(
            "/api/auth/login/2fa", json={"challenge": challenge, "code": codes[0]}
        )
        assert response.status_code == expected
    client.cookies.clear()
    challenge = login(client).json()["challenge"]
    client.post("/api/auth/login/2fa", json={"challenge": challenge, "code": codes[1]})
    assert client.get("/api/auth/2fa").json()["recovery_codes_left"] == 6


@pytest.mark.parametrize("challenge", ["garbage", "", "x" * 200])
def test_invalid_challenge(client, two_factor, challenge):
    secret, _ = two_factor
    response = client.post(
        "/api/auth/login/2fa", json={"challenge": challenge or "-", "code": code_for(secret)}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "challenge_expired"


def test_challenge_expires(client, two_factor, monkeypatch):
    from mbp.services import auth_service

    secret, _ = two_factor
    challenge = login(client).json()["challenge"]
    monkeypatch.setattr(auth_service, "CHALLENGE_TTL_SECONDS", -1)
    response = client.post(
        "/api/auth/login/2fa", json={"challenge": challenge, "code": code_for(secret)}
    )
    assert response.json()["code"] == "challenge_expired"


def test_challenge_is_not_a_session(client, two_factor):
    from mbp.security.sessions import COOKIE_NAME

    challenge = login(client).json()["challenge"]
    client.cookies.set(COOKIE_NAME, challenge)
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_codes_lock_the_account(client, two_factor):
    secret, _ = two_factor
    challenge = login(client).json()["challenge"]
    for _ in range(5):
        response = client.post(
            "/api/auth/login/2fa", json={"challenge": challenge, "code": "000000"}
        )
        assert response.status_code == 401
    # Locked: even the right code (and the right password) is refused now.
    locked = client.post(
        "/api/auth/login/2fa", json={"challenge": challenge, "code": code_for(secret, 1)}
    )
    assert locked.status_code == 401
    assert login(client).json().get("code") == "invalid_credentials"


# --- turning it off, new recovery codes, CLI ---


def test_disable_needs_password_and_code(auth_client):
    secret, _ = enable(auth_client)
    no_code = auth_client.post(
        "/api/auth/2fa/disable", json={"password": ADMIN_PASSWORD, "code": "000000"}
    )
    assert no_code.status_code == 403
    no_password = auth_client.post(
        "/api/auth/2fa/disable", json={"password": "wrong", "code": code_for(secret, 1)}
    )
    assert no_password.status_code == 403
    ok = auth_client.post(
        "/api/auth/2fa/disable", json={"password": ADMIN_PASSWORD, "code": code_for(secret, 1)}
    )
    assert ok.status_code == 204
    assert auth_client.get("/api/auth/2fa").json()["enabled"] is False
    auth_client.cookies.clear()
    assert login(auth_client).json()["two_factor_required"] is False


def test_regenerate_recovery_codes(auth_client):
    secret, old = enable(auth_client)
    response = auth_client.post(
        "/api/auth/2fa/recovery-codes",
        json={"password": ADMIN_PASSWORD, "code": code_for(secret, 1)},
    )
    assert response.status_code == 200
    new = response.json()["recovery_codes"]
    assert set(new).isdisjoint(old)
    auth_client.cookies.clear()
    challenge = login(auth_client).json()["challenge"]
    stale = auth_client.post("/api/auth/login/2fa", json={"challenge": challenge, "code": old[0]})
    assert stale.status_code == 401


def test_show_key_for_another_device(auth_client):
    secret, _ = enable(auth_client)
    wrong = auth_client.post(
        "/api/auth/2fa/key", json={"password": ADMIN_PASSWORD, "code": "000000"}
    )
    assert wrong.status_code == 403
    assert wrong.json()["fields"] == {"code": "invalid_code"}
    bad_password = auth_client.post(
        "/api/auth/2fa/key", json={"password": "wrong", "code": code_for(secret, 1)}
    )
    assert bad_password.status_code == 403
    response = auth_client.post(
        "/api/auth/2fa/key", json={"password": ADMIN_PASSWORD, "code": code_for(secret, 1)}
    )
    assert response.status_code == 200
    body = response.json()
    # The same key, so every device shows the same codes; the old ones keep working.
    assert body["secret"] == secret
    assert body["qr_svg"].startswith("data:image/svg+xml")
    assert secret in body["otpauth_uri"]
    status = auth_client.get("/api/auth/2fa").json()
    assert status == {"enabled": True, "recovery_codes_left": 8}


def test_show_key_needs_two_factor_on(auth_client):
    response = auth_client.post(
        "/api/auth/2fa/key", json={"password": ADMIN_PASSWORD, "code": "123456"}
    )
    assert response.status_code == 409


def test_cli_turns_it_off(auth_client, capsys):
    from mbp.cli import main

    enable(auth_client)
    assert main(["disable-2fa", ADMIN_USERNAME]) == 0
    assert "turned off" in capsys.readouterr().out
    assert auth_client.get("/api/auth/2fa").json()["enabled"] is False
    assert main(["disable-2fa", "nobody"]) == 1


def test_secret_and_codes_never_logged(auth_client, caplog):
    caplog.set_level(logging.DEBUG)
    secret, codes = enable(auth_client)
    auth_client.cookies.clear()
    challenge = login(auth_client).json()["challenge"]
    auth_client.post("/api/auth/login/2fa", json={"challenge": challenge, "code": codes[0]})
    assert secret not in caplog.text
    assert all(code not in caplog.text for code in codes)
