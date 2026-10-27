"""Web servers: the panel's API over the agent, read-only mode, the audit log, health checks,
certificate alerts and a project's domains after a deploy."""

from datetime import timedelta

import httpx
import pytest

from mbp.api.errors import ApiError
from mbp.db import get_sessionmaker, utcnow
from mbp.models import AlertState, NotificationLog, WebAction
from tests.api.test_projects import create as create_project
from tests.api.test_projects import deploy
from tests.unit.test_webmanage import NGINX_CONF, SHOP, make_cert
from tests.unit.test_webserver import debian_nginx

SITE = "/etc/nginx/sites-available/shop"


@pytest.fixture
def nginx(fake_host):
    fake_host.write("/etc/nginx/nginx.conf", NGINX_CONF)
    fake_host.write(SITE, SHOP)
    fake_host.link("/etc/nginx/sites-enabled/shop", "../sites-available/shop")
    fake_host.write("/var/log/nginx/shop.access.log", "GET / 200\nGET /x 404\n")
    return fake_host


def actions(db) -> list[tuple[str, str, str]]:
    db.expire_all()
    rows = db.query(WebAction).order_by(WebAction.id).all()
    return [(a.action, a.target, a.result) for a in rows]


def test_lists_the_sites_of_the_current_server(containers_client, fake_host):
    response = containers_client.get("/api/webservers")
    assert response.status_code == 200
    assert response.json() == {"available": False, "servers": []}
    debian_nginx(fake_host.root)
    body = containers_client.get("/api/webservers").json()
    assert body["available"] is True
    [nginx] = body["servers"]
    names = {name for site in nginx["sites"] for name in site["names"]}
    assert names == {"shop.example", "www.shop.example", "old.example"}
    # Internal details (raw listen lines, key files) stay in the agent.
    assert "certificate_key" not in nginx["sites"][0]


def test_unknown_server(containers_client):
    assert containers_client.get("/api/webservers", params={"server": 999}).status_code == 404


def test_an_outdated_agent_is_named(containers_client, app, monkeypatch):
    def old_agent(self, method, path, *args, **kwargs):
        raise ApiError(404, "agent_error")

    monkeypatch.setattr(type(app.state.agent), "_call", old_agent)
    response = containers_client.get("/api/webservers")
    assert (response.status_code, response.json()["code"]) == (409, "agent_outdated")


def test_status_test_and_reload(containers_client, nginx, db):
    [status] = containers_client.get("/api/webservers/-/status").json()["servers"]
    assert (status["state"], status["version"]) == ("active", "1.24.0")
    assert status["panel_reload"] is None
    assert containers_client.post("/api/webservers/nginx/test").json()["ok"] is True
    response = containers_client.post("/api/webservers/nginx/control/reload")
    assert response.status_code == 200 and response.json()["ok"] is True
    assert actions(db) == [("reload", "", "ok")]
    [status] = containers_client.get("/api/webservers/-/status").json()["servers"]
    assert status["panel_reload"] is not None
    assert containers_client.post("/api/webservers/nginx/control/stop").status_code == 422
    assert containers_client.post("/api/webservers/iis/test").status_code == 422


def test_edit_and_rollback(containers_client, nginx, db):
    file = containers_client.get("/api/webservers/nginx/file", params={"path": SITE}).json()
    assert file["content"] == SHOP
    bad = containers_client.put(
        "/api/webservers/nginx/file",
        json={"path": SITE, "content": SHOP + "BROKEN", "sha256": file["sha256"]},
    ).json()
    assert (bad["ok"], bad["code"]) == (False, "config_test_failed")
    assert "unexpected BROKEN" in bad["output"]
    assert nginx.read(SITE) == SHOP
    good = containers_client.put(
        "/api/webservers/nginx/file",
        json={"path": SITE, "content": SHOP.replace("3000", "3001"), "sha256": file["sha256"]},
    ).json()
    assert good["ok"] is True
    stale = containers_client.put(
        "/api/webservers/nginx/file",
        json={"path": SITE, "content": SHOP, "sha256": file["sha256"]},
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "file_changed")
    [backup] = containers_client.get("/api/webservers/nginx/backups", params={"path": SITE}).json()[
        "backups"
    ]
    old = containers_client.get(
        "/api/webservers/nginx/backup", params={"path": SITE, "name": backup}
    ).json()
    assert old["content"] == SHOP
    restored = containers_client.post(
        "/api/webservers/nginx/restore", json={"path": SITE, "backup": backup}
    ).json()
    assert restored["ok"] is True and nginx.read(SITE) == SHOP
    assert [a[0] + ":" + a[2] for a in actions(db)] == [
        "edit:config_test_failed",
        "edit:ok",
        "edit:file_changed",
        "restore:ok",
    ]
    outside = containers_client.get("/api/webservers/nginx/file", params={"path": "/etc/shadow"})
    assert (outside.status_code, outside.json()["code"]) == (403, "path_not_allowed")


def test_read_only_refuses_every_change(containers_client, nginx, db):
    settings = containers_client.get("/api/webservers/-/settings").json()
    assert settings["read_only"] is False and settings["cert_warning_days"] == 14
    saved = containers_client.put(
        "/api/webservers/-/settings", json={**settings, "read_only": True, "acme_email": "ops@x.io"}
    )
    assert saved.status_code == 200 and saved.json()["acme_email"] == "ops@x.io"
    bad = containers_client.put("/api/webservers/-/settings", json={**settings, "acme_email": "x"})
    assert bad.status_code == 422
    for method, url, body in [
        ("POST", "/api/webservers/nginx/control/reload", None),
        ("POST", "/api/webservers/nginx/enabled", {"path": SITE, "enabled": False}),
        ("POST", "/api/webservers/nginx/maintenance", {"path": SITE, "on": True}),
        ("POST", "/api/webservers/-/certbot/renew", None),
    ]:
        response = containers_client.request(method, url, json=body)
        assert (response.status_code, response.json()["code"]) == (403, "webservers_read_only")
    assert nginx.exists("/etc/nginx/sites-enabled/shop")
    assert {a[2] for a in actions(db)} == {"webservers_read_only"}
    # Reading still works.
    assert (
        containers_client.get("/api/webservers/nginx/file", params={"path": SITE}).status_code
        == 200
    )


def test_sites_enable_maintenance_and_create(containers_client, nginx, db):
    off = containers_client.post(
        "/api/webservers/nginx/enabled", json={"path": SITE, "enabled": False}
    ).json()
    assert off["ok"] is True and not nginx.exists("/etc/nginx/sites-enabled/shop")
    containers_client.post("/api/webservers/nginx/enabled", json={"path": SITE, "enabled": True})
    on = containers_client.post(
        "/api/webservers/nginx/maintenance", json={"path": SITE, "on": True}
    ).json()
    assert on["ok"] is True
    [nginx_list] = containers_client.get("/api/webservers").json()["servers"]
    shop = [s for s in nginx_list["sites"] if s["file"] == SITE]
    assert all(s["maintenance"] and s["enabled"] for s in shop)
    containers_client.post("/api/webservers/nginx/maintenance", json={"path": SITE, "on": False})
    created = containers_client.post(
        "/api/webservers/nginx/sites",
        json={"template": "static", "domains": ["docs.example"], "root": "/var/www/docs"},
    )
    assert created.status_code == 201 and created.json()["ok"] is True
    assert nginx.exists("/etc/nginx/sites-enabled/docs-example")
    invalid = containers_client.post(
        "/api/webservers/nginx/sites",
        json={"template": "proxy", "domains": ["x.example"], "target": "file:///etc"},
    )
    assert (invalid.status_code, invalid.json()["code"]) == (400, "invalid_target")
    assert [a[0] for a in actions(db)] == [
        "disable",
        "enable",
        "maintenance_on",
        "maintenance_off",
        "create",
        "create",
    ]


def test_logs_and_certificates(containers_client, nginx):
    logs = containers_client.get(
        "/api/webservers/nginx/logs",
        params={"path": "/var/log/nginx/access.log", "lines": 5},
    )
    # Declared, but the file does not exist.
    assert (logs.status_code, logs.json()["code"]) == (409, "log_unreadable")
    lines = containers_client.get(
        "/api/webservers/nginx/logs",
        params={"path": "/var/log/nginx/shop.access.log", "lines": 1},
    ).json()
    assert lines == {"path": "/var/log/nginx/shop.access.log", "lines": ["GET /x 404"]}
    nginx.write("/etc/ssl/shop.pem", make_cert(30))
    certs = containers_client.get("/api/webservers/-/certificates").json()["certificates"]
    assert certs["/etc/ssl/shop.pem"]["names"] == ["shop.example"]
    sockets = containers_client.get("/api/webservers/-/php-sockets").json()
    assert sockets == {"sockets": []}
    nginx.write("/run/php/php8.2-fpm.sock", "")
    sockets = containers_client.get("/api/webservers/-/php-sockets").json()
    assert sockets == {"sockets": ["unix:/run/php/php8.2-fpm.sock"]}


def test_certbot_jobs_are_audited(containers_client, nginx, db):
    containers_client.put(
        "/api/webservers/-/settings",
        json={
            "read_only": False,
            "cert_warning_days": 14,
            "check_interval_minutes": 5,
            "check_timeout_seconds": 10,
            "check_failures": 2,
            "acme_email": "ops@shop.example",
        },
    )
    status = containers_client.get("/api/webservers/-/certbot").json()
    assert status["installed"] is True and status["auto_renew"] == "certbot.timer"
    response = containers_client.post(
        "/api/webservers/nginx/certbot/issue", json={"domains": ["shop.example"]}
    )
    assert response.status_code == 202
    job = response.json()
    assert actions(db) == [("certbot_issue", "shop.example", "running")]
    done = containers_client.get(f"/api/webservers/-/jobs/{job['id']}").json()
    assert done["status"] == "success"
    assert actions(db) == [("certbot_issue", "shop.example", "ok")]
    assert any("-m ops@shop.example" in call for call in nginx.calls())
    assert containers_client.get("/api/webservers/-/jobs/" + "0" * 32).status_code == 404
    assert containers_client.get("/api/webservers/-/jobs/../x").status_code == 404
    wildcard = containers_client.post(
        "/api/webservers/nginx/certbot/issue", json={"domains": ["*.shop.example"]}
    )
    assert wildcard.json()["code"] == "wildcard_not_supported"


# --- health checks ---


class Sites:
    """A MockTransport whose answers per URL can change during a test."""

    def __init__(self) -> None:
        self.answers: dict[str, int | Exception] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        answer = self.answers.get(str(request.url), 200)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer)


def test_health_checks_alert_once_and_recover(containers_client, app, db):
    sites = Sites()
    monitor = app.state.web_monitor
    monitor.transport = httpx.MockTransport(sites)
    response = containers_client.post(
        "/api/webservers/-/checks", json={"url": "https://shop.example/"}
    )
    assert response.status_code == 201
    check = response.json()
    assert check["status"] is None and check["recent"] == []
    duplicate = containers_client.post(
        "/api/webservers/-/checks", json={"url": "https://shop.example/"}
    )
    assert duplicate.json()["code"] == "check_exists"
    for bad in ("ftp://x.example/", "https://user:pw@x.example/", "https://"):
        assert (
            containers_client.post("/api/webservers/-/checks", json={"url": bad}).status_code == 422
        )

    run = containers_client.post(f"/api/webservers/-/checks/{check['id']}/run").json()
    assert (run["status"], run["last_code"], run["uptime"]) == ("up", 200, 100.0)

    sites.answers["https://shop.example/"] = 502
    first = containers_client.post(f"/api/webservers/-/checks/{check['id']}/run").json()
    assert (first["status"], first["failures"]) == ("up", 1)
    sites.answers["https://shop.example/"] = httpx.ConnectTimeout("slow")
    second = containers_client.post(f"/api/webservers/-/checks/{check['id']}/run").json()
    assert (second["status"], second["last_error"]) == ("down", "timeout")
    third = containers_client.post(f"/api/webservers/-/checks/{check['id']}/run").json()
    assert third["failures"] == 3
    sites.answers["https://shop.example/"] = 200
    back = containers_client.post(f"/api/webservers/-/checks/{check['id']}/run").json()
    assert back["status"] == "up" and back["uptime"] == 40.0
    assert [r["ok"] for r in back["recent"]] == [True, False, False, False, True]

    app.state.notifier.close()
    db.expire_all()
    events = [
        (n.event, n.params.get("kind"))
        for n in db.query(NotificationLog).order_by(NotificationLog.id)
    ]
    assert events == [("site_down", None), ("recovered", "site_down")]

    paused = containers_client.patch(
        f"/api/webservers/-/checks/{check['id']}", json={"enabled": False}
    ).json()
    assert paused["enabled"] is False
    assert containers_client.delete(f"/api/webservers/-/checks/{check['id']}").status_code == 204
    assert containers_client.get("/api/webservers/-/checks").json() == {"checks": []}


def test_due_checks_only(app, auth_client, db):
    from mbp.models import WebCheck
    from mbp.repositories.server_repository import ServerRepository

    sites = Sites()
    monitor = app.state.web_monitor
    monitor.transport = httpx.MockTransport(sites)
    local = ServerRepository(db).local()
    fresh = WebCheck(server_id=local.id, url="https://a.example/", enabled=True, failures=0)
    recent = WebCheck(
        server_id=local.id,
        url="https://b.example/",
        enabled=True,
        failures=0,
        last_checked_at=utcnow() - timedelta(minutes=1),
    )
    off = WebCheck(server_id=local.id, url="https://c.example/", enabled=False, failures=0)
    db.add_all([fresh, recent, off])
    db.commit()
    monitor.run_checks()
    db.expire_all()
    assert fresh.last_checked_at is not None
    assert recent.last_checked_at < utcnow() - timedelta(seconds=30)
    assert off.last_checked_at is None


def test_certificate_alerts(containers_client, app, nginx, db):
    nginx.write("/etc/ssl/shop.pem", make_cert(5))
    monitor = app.state.web_monitor
    [event] = monitor.check_certificates(force=True)
    assert event.type == "cert_expiring"
    assert event.params["days"] in (4, 5) and event.params["names"] == ["shop.example"]
    assert monitor.check_certificates(force=True) == []  # announced once
    assert db.query(AlertState).count() == 1
    nginx.write("/etc/ssl/shop.pem", make_cert(80))
    [recovered] = monitor.check_certificates(force=True)
    assert (recovered.type, recovered.params["kind"]) == ("recovered", "cert")
    # Turned off: nothing more.
    nginx.write("/etc/ssl/shop.pem", make_cert(1))
    containers_client.put(
        "/api/webservers/-/settings",
        json={
            "read_only": False,
            "cert_warning_days": 0,
            "check_interval_minutes": 5,
            "check_timeout_seconds": 10,
            "check_failures": 2,
        },
    )
    assert monitor.check_certificates(force=True) == []


# --- projects ---


def test_a_deploy_configures_the_projects_domains(containers_client, nginx, db):
    bad = containers_client.post(
        "/api/projects",
        json={
            "name": "app",
            "repo_url": "https://github.com/acme/app.git",
            "web_domains": ["app.example"],
        },
    )
    assert bad.status_code == 422
    project = create_project(
        containers_client,
        name="app",
        auth_type="none",
        credential=None,
        web_domains=["App.example", "shop.example"],
        web_target="http://127.0.0.1:8080",
    )
    assert project["web_domains"] == ["app.example", "shop.example"]
    done = deploy(containers_client, project["id"])
    assert done["status"] == "success"
    log = containers_client.get(f"/api/deployments/{done['id']}").json()["log"]
    assert "app.example now proxied to http://127.0.0.1:8080" in log
    # shop.example already had a site: only app.example was added.
    text = nginx.read("/etc/nginx/sites-available/app-example")
    assert "server_name app.example;" in text
    assert actions(db) == [("create", "app.example", "ok")]
    again = deploy(containers_client, project["id"])
    log = containers_client.get(f"/api/deployments/{again['id']}").json()["log"]
    assert "already configured" in log
    get_sessionmaker()().close()
