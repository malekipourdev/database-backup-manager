"""The external API (/api/v1): keys, scopes, limits, request log, CORS, documentation."""

from datetime import timedelta

import pytest

from mbp.apiaccess.keys import SHOWN, generate_key, hash_key, limiter
from mbp.apiaccess.service import cors_origins
from mbp.db import utcnow
from mbp.models import ApiKey, ApiRequestLog, WebAction
from tests.conftest import ADMIN_PASSWORD, create_instance


@pytest.fixture(autouse=True)
def _fresh_limits():
    limiter.clear()
    cors_origins.forget()
    yield
    limiter.clear()
    cors_origins.forget()


def make_key(db, admin, scopes=("*",), **fields) -> tuple[ApiKey, str]:
    secret = generate_key()
    key = ApiKey(
        name=fields.pop("name", "erp"),
        prefix=secret[:SHOWN],
        secret_hash=hash_key(secret),
        scopes=list(scopes),
        allowed_ips=fields.pop("allowed_ips", []),
        rate_limit=fields.pop("rate_limit", 600),
        enabled=fields.pop("enabled", True),
        admin_id=admin.id,
        request_count=0,
        **fields,
    )
    db.add(key)
    db.commit()
    return key, secret


def bearer(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"}


# --- managing keys from the panel ---


def test_creating_a_key_needs_the_password_and_shows_the_secret_once(auth_client):
    body = {"name": "erp", "scopes": ["projects:read"], "password": "wrong"}
    response = auth_client.post("/api/api-access/keys", json=body)
    assert response.status_code == 403
    assert response.json()["code"] == "wrong_password"

    body["password"] = ADMIN_PASSWORD
    response = auth_client.post("/api/api-access/keys", json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    secret = created["secret"]
    assert secret.startswith("mbp_") and len(secret) > 40
    assert created["key"]["prefix"] == secret[:SHOWN]
    assert created["key"]["scopes"] == ["projects:read"]

    listed = auth_client.get("/api/api-access/keys").json()
    assert len(listed) == 1
    assert secret not in str(listed)
    me = auth_client.get("/api/v1/me", headers=bearer(secret))
    assert me.status_code == 200
    assert me.json()["name"] == "erp"
    assert me.json()["admin"] == "admin"


def test_unknown_scopes_and_bad_networks_are_refused(auth_client):
    body = {"name": "x", "scopes": ["projects:delete"], "password": ADMIN_PASSWORD}
    response = auth_client.post("/api/api-access/keys", json=body)
    assert response.status_code == 422
    assert response.json()["fields"] == {"scopes": "unknown"}
    body = {"name": "x", "scopes": ["*"], "allowed_ips": ["nope"], "password": ADMIN_PASSWORD}
    response = auth_client.post("/api/api-access/keys", json=body)
    assert response.status_code == 422
    assert response.json()["fields"] == {"allowed_ips": "value_error"}


def test_scopes_are_normalised(auth_client):
    body = {
        "name": "x",
        "scopes": ["webhooks:read", "projects:read", "projects:read"],
        "password": ADMIN_PASSWORD,
    }
    key = auth_client.post("/api/api-access/keys", json=body).json()["key"]
    assert key["scopes"] == ["projects:read", "webhooks:read"]
    body["scopes"] = ["projects:read", "*"]
    key = auth_client.post("/api/api-access/keys", json=body).json()["key"]
    assert key["scopes"] == ["*"]


def test_rotating_replaces_the_secret(auth_client, db, admin):
    key, old = make_key(db, admin)
    response = auth_client.post(
        f"/api/api-access/keys/{key.id}/rotate", json={"password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200
    new = response.json()["secret"]
    assert auth_client.get("/api/v1/me", headers=bearer(old)).status_code == 401
    assert auth_client.get("/api/v1/me", headers=bearer(new)).status_code == 200
    assert response.json()["key"]["rotated_at"] is not None


def test_update_and_delete(auth_client, db, admin):
    key, secret = make_key(db, admin, expires_at=utcnow() + timedelta(days=1))
    response = auth_client.patch(
        f"/api/api-access/keys/{key.id}",
        json={"name": "crm", "scopes": ["servers:read"], "rate_limit": 0, "expires_at": None},
    )
    assert response.status_code == 200
    out = response.json()
    assert (out["name"], out["scopes"], out["rate_limit"], out["expires_at"]) == (
        "crm",
        ["servers:read"],
        0,
        None,
    )
    # Omitted fields are kept.
    out = auth_client.patch(f"/api/api-access/keys/{key.id}", json={"enabled": False}).json()
    assert out["name"] == "crm" and out["enabled"] is False
    assert auth_client.delete(f"/api/api-access/keys/{key.id}").status_code == 204
    assert auth_client.get("/api/v1/me", headers=bearer(secret)).status_code == 401
    assert auth_client.delete(f"/api/api-access/keys/{key.id}").status_code == 404


def test_keys_cannot_manage_keys(client, db, admin):
    _, secret = make_key(db, admin)
    response = client.get("/api/api-access/keys", headers=bearer(secret))
    assert response.status_code == 401
    assert client.get("/api/v1/api-access/keys", headers=bearer(secret)).status_code == 404


# --- authentication ---


def test_key_in_either_header(client, db, admin):
    _, secret = make_key(db, admin)
    assert client.get("/api/v1/instances", headers=bearer(secret)).status_code == 200
    assert client.get("/api/v1/instances", headers={"X-API-Key": secret}).status_code == 200


def test_missing_and_wrong_keys(client):
    response = client.get("/api/v1/instances")
    assert response.status_code == 401
    assert response.json() == {"code": "api_key_missing"}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    response = client.get("/api/v1/instances", headers=bearer("mbp_nope"))
    assert response.json() == {"code": "api_key_invalid"}


def test_the_session_cookie_does_not_open_the_external_api(auth_client):
    response = auth_client.get("/api/v1/instances")
    assert response.status_code == 401
    assert response.json() == {"code": "api_key_missing"}


def test_a_key_does_not_open_the_dashboard_api(client, db, admin):
    _, secret = make_key(db, admin)
    response = client.get("/api/instances", headers=bearer(secret))
    assert response.json() == {"code": "not_authenticated"}


def test_no_csrf_header_needed(app, db, admin):
    from fastapi.testclient import TestClient

    _, secret = make_key(db, admin)
    with TestClient(app) as plain:
        response = plain.post(
            "/api/v1/project-folders", json={"name": "shop"}, headers=bearer(secret)
        )
    assert response.status_code == 201, response.text


def test_disabled_expired_and_switched_off(auth_client, client, db, admin):
    key, secret = make_key(db, admin, enabled=False)
    assert client.get("/api/v1/me", headers=bearer(secret)).json() == {"code": "api_key_disabled"}
    key.enabled = True
    key.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    response = client.get("/api/v1/me", headers=bearer(secret))
    assert (response.status_code, response.json()) == (401, {"code": "api_key_expired"})
    key.expires_at = None
    db.commit()
    assert client.get("/api/v1/me", headers=bearer(secret)).status_code == 200

    settings = auth_client.get("/api/api-access/settings").json()
    auth_client.put("/api/api-access/settings", json={**settings, "enabled": False})
    response = client.get("/api/v1/me", headers=bearer(secret))
    assert (response.status_code, response.json()) == (403, {"code": "api_disabled"})


def test_allowed_addresses(client, db, admin):
    _, secret = make_key(db, admin, allowed_ips=["203.0.113.0/24", "2001:db8::1/128"])
    headers = bearer(secret)
    response = client.get("/api/v1/me", headers={**headers, "X-Forwarded-For": "198.51.100.4"})
    assert response.status_code == 403
    assert response.json() == {"code": "ip_not_allowed", "detail": "198.51.100.4"}
    ok = client.get("/api/v1/me", headers={**headers, "X-Forwarded-For": "203.0.113.9"})
    assert ok.status_code == 200 and ok.json()["ip"] == "203.0.113.9"
    # Only the address the panel's proxy appended counts, not what the client claims.
    spoofed = client.get(
        "/api/v1/me", headers={**headers, "X-Forwarded-For": "203.0.113.9, 198.51.100.4"}
    )
    assert spoofed.status_code == 403
    v6 = client.get("/api/v1/me", headers={**headers, "X-Forwarded-For": "2001:db8::1"})
    assert v6.status_code == 200


def test_extra_proxy_hops(client, db, admin, monkeypatch):
    from mbp.config import get_settings

    monkeypatch.setattr(get_settings(), "extra_proxy_hops", 1)
    _, secret = make_key(db, admin, allowed_ips=["203.0.113.9"])
    response = client.get(
        "/api/v1/me",
        headers={**bearer(secret), "X-Forwarded-For": "1.1.1.1, 203.0.113.9, 172.18.0.1"},
    )
    assert response.status_code == 200


# --- scopes ---


def test_read_scope_reads_but_does_not_write(client, db, admin):
    _, secret = make_key(db, admin, scopes=["projects:read"])
    headers = bearer(secret)
    assert client.get("/api/v1/projects", headers=headers).status_code == 200
    assert client.get("/api/v1/project-folders", headers=headers).status_code == 200
    response = client.post("/api/v1/project-folders", json={"name": "x"}, headers=headers)
    assert response.status_code == 403
    assert response.json() == {"code": "insufficient_scope", "detail": "projects:write"}
    response = client.get("/api/v1/instances", headers=headers)
    assert response.json() == {"code": "insufficient_scope", "detail": "instances:read"}


def test_write_includes_read(client, db, admin):
    _, secret = make_key(db, admin, scopes=["projects:write"])
    assert client.get("/api/v1/projects", headers=bearer(secret)).status_code == 200
    response = client.post("/api/v1/project-folders", json={"name": "x"}, headers=bearer(secret))
    assert response.status_code == 201


def test_previews_only_need_read(client, db, admin):
    _, secret = make_key(db, admin, scopes=["schedules:read"])
    response = client.post(
        "/api/v1/schedules/preview",
        json={"cron": "0 3 * * *", "timezone": "UTC"},
        headers=bearer(secret),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["next_runs"]) > 0


def test_downloading_backups_needs_its_own_scope(client, db, admin):
    _, secret = make_key(db, admin, scopes=["backups:write"])
    response = client.get("/api/v1/backups/runs/1/download", headers=bearer(secret))
    assert response.json() == {"code": "insufficient_scope", "detail": "backups:download"}
    _, secret = make_key(db, admin, scopes=["backups:download"])
    response = client.get("/api/v1/backups/runs/1/download", headers=bearer(secret))
    assert response.status_code == 404


def test_the_same_data_as_the_dashboard(auth_client, client, db, admin, probe_ok):
    create_instance(auth_client, name="prod")
    _, secret = make_key(db, admin, scopes=["instances:read"])
    via_key = client.get("/api/v1/instances", headers=bearer(secret)).json()
    assert via_key == auth_client.get("/api/instances").json()
    assert via_key[0]["name"] == "prod"


# --- limits and log ---


def test_rate_limit(client, db, admin):
    _, secret = make_key(db, admin, rate_limit=2)
    first = client.get("/api/v1/me", headers=bearer(secret))
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert client.get("/api/v1/me", headers=bearer(secret)).status_code == 200
    third = client.get("/api/v1/me", headers=bearer(secret))
    assert third.status_code == 429
    assert third.json() == {"code": "rate_limited"}
    assert 1 <= int(third.headers["Retry-After"]) <= 60
    assert third.headers["X-RateLimit-Remaining"] == "0"


def test_requests_are_logged(auth_client, client, db, admin):
    key, secret = make_key(db, admin, scopes=["projects:read"])
    client.get("/api/v1/projects", headers=bearer(secret))
    client.get("/api/v1/instances", headers={**bearer(secret), "X-Forwarded-For": "192.0.2.5"})
    rows = db.query(ApiRequestLog).order_by(ApiRequestLog.id).all()
    assert [(r.method, r.path, r.status, r.error) for r in rows] == [
        ("GET", "/projects", 200, None),
        ("GET", "/instances", 403, "insufficient_scope"),
    ]
    assert rows[1].ip == "192.0.2.5"
    page = auth_client.get("/api/api-access/requests").json()
    assert [i["path"] for i in page["items"]] == ["/instances", "/projects"]
    assert page["items"][0]["key_name"] == "erp"
    errors = auth_client.get("/api/api-access/requests", params={"errors": True}).json()
    assert [i["status"] for i in errors["items"]] == [403]
    listed = auth_client.get("/api/api-access/keys").json()[0]
    assert (listed["request_count"], listed["requests_24h"], listed["errors_24h"]) == (2, 2, 1)
    assert listed["last_used_ip"] == "192.0.2.5"


def test_request_log_pages(auth_client, client, db, admin):
    _, secret = make_key(db, admin)
    for _ in range(5):
        client.get("/api/v1/me", headers=bearer(secret))
    first = auth_client.get("/api/api-access/requests", params={"limit": 3}).json()
    assert len(first["items"]) == 3 and first["next_before"] is not None
    rest = auth_client.get(
        "/api/api-access/requests", params={"limit": 3, "before": first["next_before"]}
    ).json()
    assert len(rest["items"]) == 2 and rest["next_before"] is None


def test_changes_are_audited_as_the_key(client, db, admin):
    """A refused change (read-only web servers) is still in the web servers' activity log."""
    _, secret = make_key(db, admin, name="deployer", scopes=["webservers:write"])
    client.put(
        "/api/v1/webservers/-/settings",
        json={
            "read_only": True,
            "cert_warning_days": 14,
            "check_interval_minutes": 5,
            "check_timeout_seconds": 10,
            "check_failures": 2,
            "acme_email": None,
        },
        headers=bearer(secret),
    )
    response = client.post("/api/v1/webservers/nginx/control/reload", headers=bearer(secret))
    assert response.json()["code"] == "webservers_read_only"
    action = db.query(WebAction).one()
    assert (action.actor, action.source) == ("admin (API: deployer)", "api")


# --- CORS ---


def test_cors(auth_client, client, db, admin):
    _, secret = make_key(db, admin)
    origin = "https://app.example.com"
    preflight = {"Origin": origin, "Access-Control-Request-Method": "GET"}
    assert client.options("/api/v1/me", headers=preflight).status_code == 403

    settings = auth_client.get("/api/api-access/settings").json()
    response = auth_client.put(
        "/api/api-access/settings", json={**settings, "cors_origins": [origin + "/"]}
    )
    assert response.json()["cors_origins"] == [origin]
    response = client.options("/api/v1/me", headers=preflight)
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
    response = client.get("/api/v1/me", headers={**bearer(secret), "Origin": origin})
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "X-RateLimit-Remaining" in response.headers["Access-Control-Expose-Headers"]
    other = client.get("/api/v1/me", headers={**bearer(secret), "Origin": "https://evil.test"})
    assert "Access-Control-Allow-Origin" not in other.headers
    # Never for the dashboard's own API.
    response = client.get("/api/health", headers={"Origin": origin})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_bad_origins_are_refused(auth_client):
    settings = auth_client.get("/api/api-access/settings").json()
    response = auth_client.put(
        "/api/api-access/settings", json={**settings, "cors_origins": ["app.example.com"]}
    )
    assert response.status_code == 422


# --- documentation ---


def test_openapi_document(client, app):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "DevOps Manager API"
    paths = spec["paths"]
    assert all(path.startswith("/api/v1/") for path in paths)
    assert not any("/auth" in path or "api-access" in path for path in paths)
    op = paths["/api/v1/projects/{project_id}/deploy"]["post"]
    assert op["x-required-scope"] == "projects:write"
    assert op["security"] == [{"bearerAuth": []}, {"apiKeyHeader": []}]
    assert op["operationId"] == "deploy_project"
    assert paths["/api/v1/backups/runs/{run_id}/download"]["get"]["x-required-scope"] == (
        "backups:download"
    )
    assert paths["/api/v1/health"]["get"]["security"] == []
    # Every operation has its own one-line summary (mbp.apiaccess.summaries).
    from mbp.apiaccess.summaries import SUMMARIES

    documented = {f"{m.upper()} {p[len('/api/v1') :]}" for p, ops in paths.items() for m in ops}
    assert documented == set(SUMMARIES)
    ids = [op["operationId"] for ops in paths.values() for op in ops.values()]
    assert len(ids) == len(set(ids))
    assert "Error" in spec["components"]["schemas"]
    assert "LoginRequest" not in spec["components"]["schemas"]
    # Every operation of the dashboard (except signing in and keys) is documented.
    dashboard = {
        (m, p) for p, ops in app.openapi()["paths"].items() for m in ops if p.startswith("/api/v1/")
    }
    assert {(m, p) for p, ops in paths.items() for m in ops} == dashboard


def test_docs_pages(client):
    for path in ("/api/v1/docs", "/api/v1/redoc"):
        response = client.get(path)
        assert response.status_code == 200
        assert "/api/v1/openapi.json" in response.text


def test_catalog(auth_client, client, db, admin):
    catalog = auth_client.get("/api/api-access/catalog").json()
    assert catalog["base_path"] == "/api/v1"
    areas = {a["area"]: a for a in catalog["areas"]}
    assert areas["projects"]["read"] > 0 and areas["projects"]["write"] > 0
    assert "backups:download" in catalog["scopes"]
    assert "backup_failed" in catalog["events"]
    _, secret = make_key(db, admin, scopes=["servers:read"])
    assert client.get("/api/v1/catalog", headers=bearer(secret)).json() == catalog
