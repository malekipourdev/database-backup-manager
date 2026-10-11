from fastapi.testclient import TestClient

from mbp.security.sessions import COOKIE_NAME
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_success_sets_secure_cookie(client, admin):
    response = login(client)
    assert response.status_code == 200
    assert response.json() == {
        "username": ADMIN_USERNAME,
        "two_factor_required": False,
        "challenge": None,
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "SameSite=Strict" in cookie
    assert "Path=/" in cookie


def test_failed_logins_are_indistinguishable(client, admin):
    wrong_password = login(client, password="nope")
    unknown_user = login(client, username="ghost")
    for _ in range(5):
        login(client, password="nope")
    locked = login(client)  # correct password, but locked out

    for response in (wrong_password, unknown_user, locked):
        assert response.status_code == 401
        assert response.json() == {"code": "invalid_credentials"}
        assert "set-cookie" not in response.headers


def test_login_requires_csrf_header(app, admin):
    with TestClient(app) as plain:
        response = plain.post(
            "/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
    assert response.status_code == 403
    assert response.json() == {"code": "csrf_failed"}


def test_login_validation_does_not_echo_password(client):
    response = client.post("/api/auth/login", json={"username": "", "password": "Echo-Me-123"})
    assert response.status_code == 422
    assert "Echo-Me-123" not in response.text


def test_me_requires_session(client, admin):
    assert client.get("/api/auth/me").status_code == 401
    login(client)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"username": ADMIN_USERNAME, "two_factor_enabled": False}


def test_logout_ends_session(client, admin):
    login(client)
    token = client.cookies.get(COOKIE_NAME)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert (
        'mbp_session=""' in response.headers["set-cookie"]
        or "Max-Age=0" in response.headers["set-cookie"]
    )
    # Even if the browser kept the cookie, the session is gone server-side.
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/auth/me").status_code == 401
