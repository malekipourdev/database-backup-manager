"""API keys and webhooks limited to some servers; requests made on behalf of a person."""

import re

import pytest

from mbp.apiaccess.keys import limiter
from mbp.apiaccess.servers import CHECKED_PARAMS
from mbp.apiaccess.webhooks import WebhookDispatcher
from mbp.db import get_sessionmaker, utcnow
from mbp.models import (
    ApiKey,
    ApiRequestLog,
    ApiWebhookDelivery,
    BackupRun,
    BackupSchedule,
    DbInstance,
    Deployment,
    Project,
    WebAction,
    WebCheck,
)
from mbp.notifications.events import Event
from mbp.security import crypto
from tests.api.test_api_webhooks import Receiver, create
from tests.api.test_external_api import bearer, make_key


class World:
    """Two servers, "a" and "b", each with a database (a backup and a schedule of it), a
    project (with a deployment) in its own folder, and a health check."""

    servers: dict[str, int]
    instances: dict[str, int]
    runs: dict[str, int]
    schedules: dict[str, int]
    projects: dict[str, int]
    deployments: dict[str, int]
    checks: dict[str, int]


@pytest.fixture
def world(auth_client, db) -> World:
    limiter.clear()
    w = World()
    w.servers, w.instances, w.runs, w.schedules = {}, {}, {}, {}
    w.projects, w.deployments, w.checks = {}, {}, {}
    for name in ("a", "b"):
        response = auth_client.post("/api/servers", json={"name": name, "host": "10.0.0.1"})
        assert response.status_code == 201, response.text
        w.servers[name] = response.json()["server"]["id"]
    for name, server_id in w.servers.items():
        instance = DbInstance(
            name=f"db-{name}",
            name_normalized=f"db-{name}",
            host="10.0.0.2",
            port=3306,
            username="u",
            password_encrypted=crypto.encrypt("pw"),
            notes="",
            server_id=server_id,
        )
        db.add(instance)
        db.flush()
        w.instances[name] = instance.id
        run = BackupRun(
            instance_id=instance.id,
            instance_name=instance.name,
            database_name="shop",
            trigger="single",
            status="success",
            requested_at=utcnow(),
        )
        schedule = BackupSchedule(
            instance_id=instance.id, name="nightly", cron="0 3 * * *", scope="all"
        )
        project = Project(
            name=f"site-{name}",
            folder=f"folder-{name}",
            server_id=server_id,
            repo_url="https://github.com/acme/site.git",
            branch="main",
            compose_file="docker-compose.yml",
            auth_type="none",
            backup_databases=[],
            backup_required=False,
        )
        check = WebCheck(server_id=server_id, url=f"https://{name}.example.com", failures=0)
        db.add_all([run, schedule, project, check])
        db.flush()
        deployment = Deployment(
            project_id=project.id,
            project_name=project.name,
            trigger="panel",
            actor="admin",
            ref="main",
            status="success",
        )
        db.add(deployment)
        db.add(
            WebAction(
                server_id=server_id,
                kind="nginx",
                action="reload",
                target="",
                actor="admin",
                source="panel",
                result="ok",
            )
        )
        db.flush()
        w.runs[name], w.schedules[name] = run.id, schedule.id
        w.projects[name], w.deployments[name], w.checks[name] = project.id, deployment.id, check.id
    db.commit()
    return w


def limited(db, admin, w: World, *names: str, scopes=("*",)) -> tuple[ApiKey, dict]:
    key, secret = make_key(db, admin, scopes, server_ids=[w.servers[n] for n in names])
    return key, bearer(secret)


def test_lists_hold_only_the_keys_servers(client, db, admin, world):
    _, auth = limited(db, admin, world, "a")
    names = [s["name"] for s in client.get("/api/v1/servers", headers=auth).json()]
    assert names == ["a"]
    instances = client.get("/api/v1/instances", headers=auth).json()
    assert [i["name"] for i in instances] == ["db-a"]
    runs = client.get("/api/v1/backups/runs", headers=auth).json()["items"]
    assert [r["id"] for r in runs] == [world.runs["a"]]
    schedules = client.get("/api/v1/schedules", headers=auth).json()
    assert [s["id"] for s in schedules] == [world.schedules["a"]]
    projects = client.get("/api/v1/projects", headers=auth).json()
    assert [p["name"] for p in projects] == ["site-a"]
    folders = client.get("/api/v1/project-folders", headers=auth).json()
    assert [f["name"] for f in folders] == ["folder-a"]
    actions = client.get("/api/v1/webservers/-/actions", headers=auth).json()["items"]
    assert {a["server_id"] for a in actions} == {world.servers["a"]}
    # Asking for the other server by name is the same as asking for one that does not exist.
    response = client.get(f"/api/v1/instances?server={world.servers['b']}", headers=auth)
    assert response.status_code == 404
    assert response.json()["code"] == "server_not_found"


def test_a_key_for_every_server_sees_everything(client, db, admin, world):
    key, secret = make_key(db, admin)
    assert key.server_ids is None
    auth = bearer(secret)
    assert len(client.get("/api/v1/servers", headers=auth).json()) == 3  # with "main"
    assert len(client.get("/api/v1/projects", headers=auth).json()) == 2
    me = client.get("/api/v1/me", headers=auth).json()
    assert me["all_servers"] is True
    assert {s["name"] for s in me["servers"]} == {"main", "a", "b"}


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/servers/{servers}", "server_not_found"),
        ("/instances/{instances}", "instance_not_found"),
        ("/instances/{instances}/backup-settings", "instance_not_found"),
        ("/instances/{instances}/schedules", "instance_not_found"),
        ("/instances/{instances}/storage-policy", "instance_not_found"),
        ("/backups/runs/{runs}", "run_not_found"),
        ("/backups/runs/{runs}/download", "run_not_found"),
        ("/schedules/{schedules}", "schedule_not_found"),
        ("/projects/{projects}", "project_not_found"),
        ("/projects/{projects}/deployments", "project_not_found"),
        ("/deployments/{deployments}", "deployment_not_found"),
        ("/containers?server={servers}", "server_not_found"),
        ("/webservers/-/checks?server={servers}", "server_not_found"),
    ],
)
def test_another_servers_things_do_not_exist(client, db, admin, world, path, code):
    _, auth = limited(db, admin, world, "a")
    ids = {name: getattr(world, name)["b"] for name in ("servers", "instances", "runs")}
    ids |= {name: getattr(world, name)["b"] for name in ("schedules", "projects", "deployments")}
    response = client.get("/api/v1" + path.format(**ids), headers=auth)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == code
    log = db.query(ApiRequestLog).order_by(ApiRequestLog.id.desc()).first()
    assert log.error == code


def test_own_things_are_reachable(client, db, admin, world):
    _, auth = limited(db, admin, world, "a")
    for path in (
        f"/servers/{world.servers['a']}",
        f"/instances/{world.instances['a']}",
        f"/backups/runs/{world.runs['a']}",
        f"/schedules/{world.schedules['a']}",
        f"/projects/{world.projects['a']}",
        f"/deployments/{world.deployments['a']}",
    ):
        response = client.get("/api/v1" + path, headers=auth)
        assert response.status_code == 200, (path, response.text)


def test_changing_another_servers_things_is_refused(client, db, admin, world):
    _, auth = limited(db, admin, world, "a")
    b = world.servers["b"]
    for method, path in (
        ("DELETE", f"/servers/{b}"),
        ("DELETE", f"/instances/{world.instances['b']}"),
        ("DELETE", f"/schedules/{world.schedules['b']}"),
        ("DELETE", f"/projects/{world.projects['b']}"),
        ("POST", f"/projects/{world.projects['b']}/deploy"),
        ("DELETE", f"/webservers/-/checks/{world.checks['b']}?server={world.servers['a']}"),
        ("POST", "/containers/web/restart"),  # the panel's own server, not the key's
    ):
        response = client.request(method, "/api/v1" + path, headers=auth, json={})
        assert response.status_code == 404, (method, path, response.text)
    assert db.get(Project, world.projects["b"]) is not None


def test_bodies_may_only_name_the_keys_servers(client, db, admin, world):
    _, auth = limited(db, admin, world, "a")
    b = world.servers["b"]
    instance = {"name": "x", "host": "h", "username": "u", "password": "p", "server_id": b}
    response = client.post("/api/v1/instances", json=instance, headers=auth)
    assert response.status_code == 422
    assert response.json()["fields"] == {"server_id": "server_not_found"}
    # Without a server the database would be the panel's own server's: not the key's either.
    response = client.post("/api/v1/instances", json={**instance, "server_id": None}, headers=auth)
    assert response.status_code == 422
    response = client.patch(
        f"/api/v1/instances/{world.instances['a']}", json={"server_id": b}, headers=auth
    )
    assert response.status_code == 422
    project = {
        "name": "new",
        "repo_url": "https://github.com/acme/new.git",
        "server_id": world.servers["a"],
    }
    for field, value in (
        ("server_id", b),
        ("build_server_id", b),
        ("backup_instance_id", world.instances["b"]),
    ):
        response = client.post("/api/v1/projects", json={**project, field: value}, headers=auth)
        assert response.status_code == 422, (field, response.text)
        assert field in response.json()["fields"]


def test_panel_wide_settings_are_read_only_or_hidden(client, db, admin, world):
    _, auth = limited(db, admin, world, "a")
    assert client.get("/api/v1/backup-settings", headers=auth).status_code == 200
    assert client.get("/api/v1/remote-storage", headers=auth).status_code == 200
    assert client.get("/api/v1/retention", headers=auth).status_code == 200
    for method, path in (
        ("PUT", "/backup-settings"),
        ("PUT", "/retention"),
        ("POST", "/retention/apply"),
        ("PUT", "/remote-storage"),
        ("POST", "/project-folders"),
        ("GET", "/notifications/settings"),
        ("GET", "/bots"),
        ("GET", "/webhooks"),
        ("POST", "/webhooks"),
    ):
        response = client.request(method, "/api/v1" + path, headers=auth, json={})
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["code"] == "server_restricted"
    # What is under one of its databases is the key's to change.
    response = client.put(
        f"/api/v1/instances/{world.instances['a']}/backup-settings",
        json={"storage_dir": None, "name_pattern": None, "compression": None},
        headers=auth,
    )
    assert response.status_code != 403, response.text


def test_a_server_added_with_the_key_joins_it(client, db, admin, world):
    key, auth = limited(db, admin, world, "a")
    response = client.post("/api/v1/servers", json={"name": "c", "host": "10.0.0.9"}, headers=auth)
    assert response.status_code == 201, response.text
    new = response.json()["server"]["id"]
    db.refresh(key)
    assert key.server_ids == sorted([world.servers["a"], new])
    names = [s["name"] for s in client.get("/api/v1/servers", headers=auth).json()]
    assert names == ["a", "c"]
    me = client.get("/api/v1/me", headers=auth).json()
    assert me["all_servers"] is False
    assert [s["name"] for s in me["servers"]] == ["a", "c"]


def test_managing_a_keys_servers(auth_client, world):
    from tests.conftest import ADMIN_PASSWORD

    body = {
        "name": "tskm",
        "scopes": ["*"],
        "server_ids": [world.servers["b"], world.servers["a"]],
        "password": ADMIN_PASSWORD,
    }
    created = auth_client.post("/api/api-access/keys", json=body)
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    assert key["server_ids"] == sorted(world.servers.values())
    response = auth_client.post("/api/api-access/keys", json={**body, "server_ids": [9999]})
    assert response.status_code == 422
    assert response.json()["fields"] == {"server_ids": "server_not_found"}
    path = f"/api/api-access/keys/{key['id']}"
    assert auth_client.patch(path, json={"name": "x"}).json()["server_ids"] == key["server_ids"]
    assert auth_client.patch(path, json={"server_ids": None}).json()["server_ids"] is None


def test_every_path_parameter_is_accounted_for(app):
    """A new route naming a server's thing in its path must be checked (CHECKED_PARAMS), or
    be one whose server comes from the `server` parameter or that is not about a server."""
    not_about_a_server = {
        "ref",  # containers: on the `server` parameter's server
        "action",
        "kind",  # web servers: same
        "job_id",
        "platform",  # bots, webhooks, folders: refused or panel-wide
        "admin_id",
        "webhook_id",
        "delivery_id",
        "folder_id",
    }

    seen = set()
    for path in app.openapi()["paths"]:
        if not path.startswith("/api/v1/"):
            continue
        for name in re.findall(r"\{(\w+)\}", path):
            seen.add(name)
            assert name in CHECKED_PARAMS or name in not_about_a_server, (path, name)
    assert set(CHECKED_PARAMS) <= seen


# --- webhooks ---


@pytest.fixture
def rx(app):
    receiver = Receiver()
    app.state.webhooks = WebhookDispatcher(
        get_sessionmaker(), background=False, transport=receiver.transport, sleep=lambda _: None
    )
    return receiver


def test_webhooks_limited_to_servers_get_only_their_events(auth_client, app, db, world, rx):
    hook = create(auth_client, name="a-only", server_ids=[world.servers["a"]])["webhook"]
    assert hook["server_ids"] == [world.servers["a"]]
    create(auth_client, name="all", url="https://all.example.com/hook")
    dispatcher = app.state.webhooks

    def targets(event: Event) -> set[str]:
        before = len(rx.requests)
        dispatcher.dispatch(event)
        return {str(r.url.host) for r in rx.requests[before:]}

    on_a = Event("site_down", "k1", {"url": "https://a"}, server_id=world.servers["a"])
    assert targets(on_a) == {"hooks.example.com", "all.example.com"}
    on_b = Event("site_down", "k2", {"url": "https://b"}, server_id=world.servers["b"])
    assert targets(on_b) == {"all.example.com"}
    # A backup's server is its database's.
    backup = Event("backup_failed", "k3", {"db": "shop"}, run_id=world.runs["a"])
    assert targets(backup) == {"hooks.example.com", "all.example.com"}
    panel_wide = Event("disk_low", "k4", {"free_percent": 3})
    assert targets(panel_wide) == {"all.example.com"}

    payload = (
        db.query(ApiWebhookDelivery)
        .filter(ApiWebhookDelivery.webhook_id == hook["id"])
        .order_by(ApiWebhookDelivery.id)
        .first()
        .payload
    )
    assert payload["server"] == {"id": world.servers["a"], "name": "a"}

    path = f"/api/webhooks/{hook['id']}"
    assert auth_client.patch(path, json={"server_ids": None}).json()["server_ids"] is None
    response = auth_client.patch(path, json={"server_ids": [12345]})
    assert response.status_code == 422


# --- on behalf of ---


def test_requests_record_who_they_were_made_for(client, db, admin, world):
    _, auth = limited(db, admin, world, "a")
    headers = {**auth, "X-MBP-On-Behalf-Of": "  Sara   Ahmadi "}
    assert client.get("/api/v1/servers", headers=headers).status_code == 200
    entry = db.query(ApiRequestLog).order_by(ApiRequestLog.id.desc()).first()
    assert entry.on_behalf_of == "Sara Ahmadi"
    assert client.get("/api/v1/servers", headers=auth).status_code == 200
    entry = db.query(ApiRequestLog).order_by(ApiRequestLog.id.desc()).first()
    assert entry.on_behalf_of is None


def test_the_log_shows_who_requests_were_made_for(auth_client, db, admin, world):
    key, secret = make_key(db, admin)
    headers = {**bearer(secret), "X-MBP-On-Behalf-Of": "Sara"}
    assert auth_client.get("/api/v1/servers", headers=headers).status_code == 200
    items = auth_client.get("/api/api-access/requests").json()["items"]
    assert items[0]["on_behalf_of"] == "Sara"
