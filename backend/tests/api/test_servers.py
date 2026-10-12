"""Several servers: adding and connecting another server's agent (HTTPS, pinned certificate,
signed requests), its containers, deploys and database backups through it."""

import gzip
import hashlib
import ssl
import time

import pytest

from mbp.db import get_sessionmaker
from mbp.models import ContainerAction, Server
from mbp.security import agent_auth
from tests.conftest import BACKUP_ROOT, INSTANCE_PAYLOAD, wait_for_run

DB_PASSWORD = INSTANCE_PAYLOAD["password"]


def add_server(client, name="edge", port=8443):
    response = client.post("/api/servers", json={"name": name, "host": "127.0.0.1", "port": port})
    assert response.status_code == 201, response.text
    return response.json()


# --- signing (unit) ---


def test_signatures_are_bound_to_the_certificate_and_time():
    header = agent_auth.sign("tok", "GET", "/v1/info", "fp1", ts=1000)
    assert agent_auth.verify(header, "tok", "GET", "/v1/info", "fp1", now=1000)
    assert not agent_auth.verify(header, "tok", "GET", "/v1/info", "fp2", now=1000)
    assert not agent_auth.verify(header, "other", "GET", "/v1/info", "fp1", now=1000)
    assert not agent_auth.verify(header, "tok", "POST", "/v1/info", "fp1", now=1000)
    assert not agent_auth.verify(header, "tok", "GET", "/v1/stats", "fp1", now=1000)
    assert not agent_auth.verify(header, "tok", "GET", "/v1/info", "fp1", now=1000 + 301)
    assert agent_auth.clock_skewed(header, now=1000 + 301)
    assert not agent_auth.verify("Bearer tok", "tok", "GET", "/v1/info", "fp1", now=1000)
    assert "tok" not in header


def test_frames_round_trip_and_detect_a_cut():
    from mbp.backups import frames

    stream = frames.encode(frames.DATA, b"abc") + frames.encode(frames.DATA, b"de")
    whole = stream + frames.end_frame(0, "warn")
    reader = frames.FrameReader([whole[i : i + 3] for i in range(0, len(whole), 3)])
    assert b"".join(reader.data()) == b"abcde"
    assert reader.end == {"returncode": 0, "stderr_tail": "warn"}

    cut = frames.FrameReader([stream])
    assert b"".join(cut.data()) == b"abcde"
    assert cut.end is None
    with pytest.raises(frames.FrameError):
        list(frames.FrameReader([stream[:-1]]).data())


# --- adding and connecting ---


def test_local_server_is_listed_first(auth_client):
    servers = auth_client.get("/api/servers").json()
    assert [(s["kind"], s["paired"]) for s in servers] == [("local", True)]


def test_add_shows_the_token_once(auth_client):
    setup = add_server(auth_client)
    token = setup["token"]
    assert len(token) >= 40
    assert f"MBP_AGENT_TOKEN={token}" in setup["install_command"]
    assert "MBP_AGENT_PORT=8443" in setup["install_command"]
    assert setup["server"]["paired"] is False
    for path in ("/api/servers", f"/api/servers/{setup['server']['id']}"):
        assert token not in auth_client.get(path).text
    with get_sessionmaker()() as db:
        row = db.get(Server, setup["server"]["id"])
        assert token not in row.token_encrypted
    duplicate = auth_client.post("/api/servers", json={"name": "EDGE", "host": "h"})
    assert duplicate.status_code == 409


def test_connect_pins_the_agents_certificate(auth_client, remote):
    assert remote["paired"] is True
    assert remote["last_error"] is None
    assert len(remote["cert_fingerprint"]) == 64
    with get_sessionmaker()() as db:
        row = db.get(Server, remote["id"])
        pem = row.cert_pem
    served = ssl.get_server_certificate(("127.0.0.1", remote["port"]))
    assert ssl.PEM_cert_to_DER_cert(served) == ssl.PEM_cert_to_DER_cert(pem)


def test_connect_with_a_wrong_token_fails(auth_client, remote_agents):
    setup = add_server(auth_client)
    port = remote_agents("not-the-servers-token")
    server_id = setup["server"]["id"]
    auth_client.patch(f"/api/servers/{server_id}", json={"port": port})
    response = auth_client.post(f"/api/servers/{server_id}/connect")
    assert (response.status_code, response.json()["code"]) == (502, "agent_unauthorized")
    server = auth_client.get(f"/api/servers/{server_id}").json()
    assert server["paired"] is False
    assert server["last_error"] == "agent_unauthorized"


def test_unreachable_server(auth_client):
    setup = add_server(auth_client, port=1)
    response = auth_client.post(f"/api/servers/{setup['server']['id']}/connect")
    assert (response.status_code, response.json()["code"]) == (503, "agent_unreachable")


def test_another_certificate_is_refused(auth_client, remote, remote_agents, docker):
    """An agent with another certificate (reinstalled, or someone in between) is not used."""
    from mbp.servers.registry import server_token

    with get_sessionmaker()() as db:
        token = server_token(db.get(Server, remote["id"]))
    other_port = remote_agents(token, name="b")
    auth_client.patch(f"/api/servers/{remote['id']}", json={"port": other_port})
    response = auth_client.get(f"/api/containers?server={remote['id']}")
    assert (response.status_code, response.json()["code"]) == (502, "agent_cert_mismatch")
    # Connecting again trusts the new certificate: that agent proved it holds the token.
    assert auth_client.post(f"/api/servers/{remote['id']}/connect").status_code == 200
    assert auth_client.get(f"/api/containers?server={remote['id']}").status_code == 200


def test_new_token_needs_a_new_connect(auth_client, remote):
    response = auth_client.post(f"/api/servers/{remote['id']}/token")
    assert response.status_code == 200
    assert response.json()["server"]["paired"] is False
    listing = auth_client.get(f"/api/containers?server={remote['id']}")
    assert (listing.status_code, listing.json()["code"]) == (409, "server_not_connected")
    # The running agent still has the old token.
    again = auth_client.post(f"/api/servers/{remote['id']}/connect")
    assert again.json()["code"] == "agent_unauthorized"


def test_local_server_cannot_be_deleted_or_rekeyed(auth_client):
    local = auth_client.get("/api/servers").json()[0]
    assert auth_client.delete(f"/api/servers/{local['id']}").json()["code"] == "server_is_local"
    assert auth_client.post(f"/api/servers/{local['id']}/token").json()["code"] == (
        "server_is_local"
    )
    renamed = auth_client.patch(f"/api/servers/{local['id']}", json={"name": "tehran-1"})
    assert renamed.json()["name"] == "tehran-1"


# --- containers on another server ---


def test_containers_of_another_server(auth_client, remote, docker):
    docker.add("api-1")
    response = auth_client.get(f"/api/containers?server={remote['id']}")
    assert response.status_code == 200, response.text
    assert [c["name"] for c in response.json()["containers"]] == ["api-1"]
    info = auth_client.get(f"/api/containers/-/info?server={remote['id']}")
    assert info.status_code == 200

    restart = auth_client.post(f"/api/containers/api-1/restart?server={remote['id']}")
    assert restart.status_code == 200, restart.text
    with get_sessionmaker()() as db:
        action = db.query(ContainerAction).one()
        assert (action.server_id, action.server_name) == (remote["id"], "edge")
    actions = auth_client.get(f"/api/containers/-/actions?server={remote['id']}").json()
    assert actions["total"] == 1 and actions["items"][0]["server_name"] == "edge"


def test_settings_are_per_server(auth_client, remote):
    put = auth_client.put(
        f"/api/containers/-/settings?server={remote['id']}",
        json={
            **auth_client.get("/api/containers/-/settings").json(),
            "read_only": True,
        },
    )
    assert put.status_code == 200
    assert auth_client.get(f"/api/containers/-/settings?server={remote['id']}").json()["read_only"]
    assert not auth_client.get("/api/containers/-/settings").json()["read_only"]


def test_server_in_use_cannot_be_deleted(auth_client, remote):
    project = auth_client.post(
        "/api/projects",
        json={
            "name": "edge-app",
            "server_id": remote["id"],
            "repo_url": "https://github.com/acme/app.git",
        },
    )
    assert project.status_code == 201, project.text
    assert project.json()["server_name"] == "edge"
    response = auth_client.delete(f"/api/servers/{remote['id']}")
    assert (response.status_code, response.json()["code"]) == (409, "server_in_use")
    auth_client.delete(f"/api/projects/{project.json()['id']}")
    assert auth_client.delete(f"/api/servers/{remote['id']}").status_code == 204


def test_deploy_on_another_server(auth_client, app, remote, agent_commands):
    app.state.deploy_runner.poll_seconds = 0.02
    project = auth_client.post(
        "/api/projects",
        json={
            "name": "edge-app",
            "server_id": remote["id"],
            "repo_url": "https://github.com/acme/app.git",
        },
    ).json()
    started = auth_client.post(f"/api/projects/{project['id']}/deploy", json={})
    assert started.status_code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        d = auth_client.get(f"/api/deployments/{started.json()['id']}").json()
        if d["status"] in ("success", "failed"):
            break
        time.sleep(0.05)
    assert d["status"] == "success", d
    assert "compose up" in agent_commands.called()
    up = next(c for c in agent_commands.calls if c["key"] == "compose up")
    assert "edge-app" in up["args"] and "projects-a" in up["cwd"]
    state = auth_client.get(f"/api/projects/{project['id']}/state").json()
    assert state["available"] is True
    moved = auth_client.put(
        f"/api/projects/{project['id']}",
        json={"name": "edge-app", "server_id": None, "repo_url": project["repo_url"]},
    )
    assert moved.status_code == 200  # None keeps the server
    local_id = auth_client.get("/api/servers").json()[0]["id"]
    refused = auth_client.put(
        f"/api/projects/{project['id']}",
        json={"name": "edge-app", "server_id": local_id, "repo_url": project["repo_url"]},
    )
    assert refused.json()["fields"] == {"server_id": "move_after_deploy"}


# --- databases on another server ---


def create_remote_instance(client, server_id, select=()):
    from mbp.models import DbSelection

    response = client.post(
        "/api/instances", json={**INSTANCE_PAYLOAD, "name": "edge-db", "server_id": server_id}
    )
    assert response.status_code == 201, response.text
    instance_id = response.json()["id"]
    if select:
        with get_sessionmaker()() as session:
            session.add_all(DbSelection(instance_id=instance_id, database_name=n) for n in select)
            session.commit()
    return instance_id


@pytest.fixture
def probe_seen(monkeypatch):
    """The connection test (here run by the agent, in this process) records its host."""
    from mbp.services import mysql_probe

    seen = []

    def fake(params, timeout=None):
        seen.append(params.host)
        return mysql_probe.ProbeResult(
            ok=True, tested_at=mysql_probe.utcnow(), server_type="mysql", server_version="8.4.3"
        )

    def listing(params, timeout=None):
        seen.append(params.host)
        return mysql_probe.ListResult(ok=True, names=["ok_shop", "mysql"])

    monkeypatch.setattr(mysql_probe, "test_connection", fake)
    monkeypatch.setattr(mysql_probe, "list_databases", listing)
    return seen


def test_local_server_is_not_a_database_route(auth_client):
    local_id = auth_client.get("/api/servers").json()[0]["id"]
    response = auth_client.post("/api/instances", json={**INSTANCE_PAYLOAD, "server_id": local_id})
    assert response.json()["fields"] == {"server_id": "invalid_server"}


def test_test_and_list_through_the_agent(auth_client, remote, probe_seen, docker):
    docker.add("shop-db")
    instance_id = create_remote_instance(auth_client, remote["id"])
    result = auth_client.post(f"/api/instances/{instance_id}/test-connection").json()
    assert result["ok"] is True and result["server_version"] == "8.4.3"
    listing = auth_client.get(f"/api/instances/{instance_id}/databases").json()
    assert listing["reachable"] is True
    assert [d["name"] for d in listing["databases"]] == ["mysql", "ok_shop"]
    # A container's name stands for its address on that server.
    unsaved = auth_client.post(
        "/api/instances/test-connection",
        json={
            **{k: INSTANCE_PAYLOAD[k] for k in ("port", "username", "password")},
            "host": "shop-db",
            "server_id": remote["id"],
        },
    )
    assert unsaved.json()["ok"] is True
    assert probe_seen[-1] == "172.18.0.5"
    assert probe_seen[0] == INSTANCE_PAYLOAD["host"]


def test_backup_through_the_agent(auth_client, remote, probe_seen):
    instance_id = create_remote_instance(auth_client, remote["id"], select=("ok_shop",))
    body = auth_client.post(f"/api/instances/{instance_id}/backups", json={"scope": "all"}).json()
    run = wait_for_run(auth_client, body["created"][0]["id"])
    assert run["status"] == "success", run
    path = BACKUP_ROOT / "edge-db" / run["file_name"]
    data = path.read_bytes()
    assert run["checksum_sha256"] == hashlib.sha256(data).hexdigest()
    assert gzip.decompress(data).rstrip().endswith(b"12:00:00")
    assert run["bytes_processed"] > 200_000


def test_failed_dump_through_the_agent_is_classified(auth_client, remote, probe_seen):
    instance_id = create_remote_instance(auth_client, remote["id"])
    for database, code in (
        ("denied_shop", "missing_privileges"),
        ("crash_shop", "connection_lost"),
    ):
        body = auth_client.post(
            f"/api/instances/{instance_id}/backups",
            json={"scope": "single", "database": database},
        ).json()
        run = wait_for_run(auth_client, body["created"][0]["id"])
        assert run["status"] == "failed"
        assert run["error_code"] == code, run
    secret = auth_client.post(
        f"/api/instances/{instance_id}/backups",
        json={"scope": "single", "database": "pwecho_shop"},
    ).json()
    run = wait_for_run(auth_client, secret["created"][0]["id"])
    assert DB_PASSWORD not in str(run)


def test_backup_when_the_server_is_down(auth_client, remote, probe_seen):
    instance_id = create_remote_instance(auth_client, remote["id"], select=("ok_shop",))
    auth_client.patch(f"/api/servers/{remote['id']}", json={"port": 1})
    body = auth_client.post(f"/api/instances/{instance_id}/backups", json={"scope": "all"}).json()
    run = wait_for_run(auth_client, body["created"][0]["id"])
    assert (run["status"], run["error_code"]) == ("failed", "agent_unreachable")


# --- alerts ---


def test_monitor_alerts_for_another_server(auth_client, app, remote, docker):
    from mbp.containers.monitor import ContainerMonitor
    from mbp.notifications.notifier import Notifier

    notifier = Notifier(get_sessionmaker(), background=False)
    monitor = ContainerMonitor(get_sessionmaker(), notifier, app.state.agents)
    web = docker.add("web")
    monitor.check()
    web.state, web.exit_code = "exited", 1
    events = monitor.check()
    remote_events = [e for e in events if e.params.get("server_id") == remote["id"]]
    assert [(e.type, e.subject) for e in remote_events] == [
        ("container_down", f"container:down:web@{remote['id']}")
    ]
    assert remote_events[0].params["server"] == "edge"
    auth_client.patch(f"/api/servers/{remote['id']}", json={"port": 1})
    events = monitor.check()
    assert ("agent_unreachable", f"agent:down@{remote['id']}") in [
        (e.type, e.subject) for e in events
    ]
    server = auth_client.get(f"/api/servers/{remote['id']}").json()
    assert server["last_error"] == "agent_unreachable"


def _dump_processes(marker: str) -> list[str]:
    import subprocess

    out = subprocess.run(["ps", "-eww", "-o", "args"], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if marker in line and "fake_dump" in line]


def test_stopping_a_backup_stops_the_dump_on_the_server(auth_client, app, remote, probe_seen):
    instance_id = create_remote_instance(auth_client, remote["id"])
    body = auth_client.post(
        f"/api/instances/{instance_id}/backups",
        json={"scope": "single", "database": "big_20000_shop"},
    ).json()
    run_id = body["created"][0]["id"]
    runner = app.state.backup_runner
    deadline = time.monotonic() + 10
    while not _dump_processes("big_20000_shop"):
        assert time.monotonic() < deadline, "the dump did not start on the server"
        time.sleep(0.05)
    time.sleep(0.5)
    with runner._lock:
        process = runner._processes[run_id]
    process.terminate()
    run = wait_for_run(auth_client, run_id)
    assert (run["status"], run["error_code"]) == ("failed", "interrupted")
    # 20 GB: it is still writing when it is stopped, so it can only end by being killed.
    deadline = time.monotonic() + 10
    while _dump_processes("big_20000_shop"):
        assert time.monotonic() < deadline, "the dump kept running on the server"
        time.sleep(0.1)
