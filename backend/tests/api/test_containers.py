"""Containers: the Docker agent, the panel's container API, rules and the audit log."""

from fastapi.testclient import TestClient

from mbp.models import ContainerAction
from tests.conftest import ADMIN_USERNAME

SECRET = "Very-Secret-42"
PANEL = {"mbp.role": "panel", "com.docker.compose.project": "mysql-backup-panel"}
SHOP = {"com.docker.compose.project": "shop", "com.docker.compose.service": "web"}


def seed(docker):
    docker.add("shop-web-1", labels=SHOP)
    docker.add(
        "shop-db-1",
        image="mysql:8.4",
        labels={**SHOP, "com.docker.compose.service": "db"},
        health="healthy",
    )
    docker.add("worker", state="exited", exit_code=1, restart_policy="no")
    docker.add("mysql-backup-panel-backend-1", labels=PANEL)


# --- agent ---


def test_agent_requires_its_token(agent_app):
    client = TestClient(agent_app)
    assert client.get("/health").json() == {"ok": True}
    assert client.get("/v1/containers").status_code == 401
    wrong = client.get("/v1/containers", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert client.post("/v1/containers/x/restart").status_code == 401


def test_agent_refuses_to_control_the_panel(docker, agent):
    from mbp.api.errors import ApiError

    seed(docker)
    try:
        agent.action("mysql-backup-panel-backend-1", "stop")
    except ApiError as exc:
        assert (exc.status, exc.code) == (403, "container_protected")
    else:
        raise AssertionError("the panel's own container was stopped")
    assert docker.containers["mysql-backup-panel-backend-1"].state == "running"


# --- listing and details ---


def test_list_groups_flags_and_problems(containers_client, docker):
    seed(docker)
    response = containers_client.get("/api/containers")
    assert response.status_code == 200
    body = response.json()
    assert body["read_only"] is False
    by_name = {c["name"]: c for c in body["containers"]}
    assert set(by_name) == {"shop-web-1", "shop-db-1", "worker", "mysql-backup-panel-backend-1"}
    web = by_name["shop-web-1"]
    assert (web["project"], web["service"], web["state"]) == ("shop", "web", "running")
    assert web["ports"] == [{"private": 80, "public": 8080, "type": "tcp"}]
    assert web["restart_policy"] == "unless-stopped"
    assert by_name["shop-db-1"]["health"] == "healthy"
    assert by_name["worker"]["problem"] == "crashed"
    assert web["problem"] is None
    panel = by_name["mysql-backup-panel-backend-1"]
    assert panel["locked"] is True and panel["panel"] == "panel"
    assert SECRET not in response.text


def test_details_show_env_names_never_values(containers_client, docker):
    seed(docker)
    response = containers_client.get("/api/containers/shop-web-1")
    assert response.status_code == 200
    body = response.json()
    assert body["env_names"] == ["DB_PASSWORD", "PATH"]
    assert body["mounts"] == [
        {"type": "volume", "source": "data", "destination": "/data", "read_only": False}
    ]
    assert body["networks"] == [{"name": "web", "ip": "172.18.0.5"}]
    assert SECRET not in response.text
    assert containers_client.get("/api/containers/nope").status_code == 404
    # Only container names / IDs ever reach the agent.
    assert containers_client.get("/api/containers/.hidden").status_code == 422


def test_unhealthy_and_restarting_are_problems(containers_client, docker):
    docker.add("api", health="unhealthy")
    docker.add("loop", state="restarting", restart_count=7)
    docker.add("stopped", state="exited", exit_code=143)
    docker.add("oom", state="exited", exit_code=137, oom_killed=True)
    by_name = {c["name"]: c for c in containers_client.get("/api/containers").json()["containers"]}
    assert by_name["api"]["problem"] == "unhealthy"
    assert by_name["loop"]["problem"] == "restarting"
    assert by_name["loop"]["restart_count"] == 7
    assert by_name["stopped"]["problem"] is None  # stopped on purpose
    assert by_name["oom"]["problem"] == "crashed"
    details = containers_client.get("/api/containers/api").json()
    assert details["health_failing_streak"] == 3
    assert details["health_last_output"] == "curl: (7) failed"


def test_logs_are_split_by_stream_and_cleaned(containers_client, docker):
    docker.add("app", logs=[("stdout", f"line {i}") for i in range(10)] + [("stderr", "boom")])
    response = containers_client.get("/api/containers/app/logs", params={"tail": 3})
    assert response.status_code == 200
    lines = response.json()["lines"]
    assert [(line["stream"], line["text"]) for line in lines] == [
        ("stdout", "line 8"),
        ("stdout", "line 9"),
        ("stderr", "boom"),
    ]
    assert lines[0]["time"] == "2026-10-11T08:00:00.000Z"
    assert containers_client.get("/api/containers/app/logs", params={"tail": 0}).status_code == 422


def test_tty_logs(containers_client, docker):
    docker.add("tty", tty=True, logs=[("stdout", "a"), ("stdout", "b")])
    lines = containers_client.get("/api/containers/tty/logs").json()["lines"]
    assert [line["text"] for line in lines] == ["a", "b"]


def test_stats_and_server_info(containers_client, docker):
    seed(docker)
    first = containers_client.get("/api/containers/-/stats").json()["stats"]
    assert set(first) == {"shop-web-1", "shop-db-1", "mysql-backup-panel-backend-1"}
    web = first["shop-web-1"]
    # Page cache (inactive_file) is not counted.
    assert web["memory_usage"] == 50 * 1024 * 1024
    assert web["memory_percent"] == round(50 * 100 / 512, 2)
    assert web["pids"] == 3 and web["net_rx"] == 1000 and web["block_read"] == 4096
    assert containers_client.get("/api/containers/worker/stats").json() == {"stats": None}

    info = containers_client.get("/api/containers/-/info").json()
    assert info["docker"]["version"] == "27.3.1"
    assert info["docker"]["running"] == 3 and info["docker"]["containers"] == 4
    assert info["host"]["memory_total"] == 8 * 1024**3
    assert info["host"]["memory_available"] == 2 * 1024**3
    assert info["host"]["load"] == [0.5, 0.4, 0.3]
    assert info["host"]["disk_total"] > 0


def test_cpu_percent_from_two_samples(containers_client, docker):
    docker.add("solo")
    first = containers_client.get("/api/containers/solo/stats").json()["stats"]
    assert first["cpu_percent"] is None
    # 1e6 container ns per 4e6 system ns, on 2 CPUs = 50%.
    again = containers_client.get("/api/containers/solo/stats").json()["stats"]
    assert again["cpu_percent"] == 50.0


# --- control, rules and audit ---


def test_restart_stop_start_are_audited(containers_client, docker, db):
    seed(docker)
    response = containers_client.post("/api/containers/shop-web-1/stop")
    assert response.status_code == 200
    assert response.json()["container"]["state"] == "exited"
    assert containers_client.post("/api/containers/shop-web-1/start").json()["container"][
        "state"
    ] == ("running")
    assert containers_client.post("/api/containers/shop-web-1/restart").status_code == 200
    assert containers_client.post("/api/containers/shop-web-1/delete").status_code == 422
    page = containers_client.get("/api/containers/-/actions").json()
    assert page["total"] == 3
    assert [(i["action"], i["result"]) for i in page["items"]] == [
        ("restart", "ok"),
        ("start", "ok"),
        ("stop", "ok"),
    ]
    item = page["items"][0]
    assert (item["actor"], item["source"], item["container"]) == (
        ADMIN_USERNAME,
        "panel",
        "shop-web-1",
    )


def test_panel_and_locked_containers_cannot_be_controlled(containers_client, docker):
    seed(docker)
    response = containers_client.post("/api/containers/mysql-backup-panel-backend-1/stop")
    assert (response.status_code, response.json()["code"]) == (403, "container_locked")
    settings = containers_client.get("/api/containers/-/settings").json()
    settings["locked"] = ["shop-db-*"]
    assert containers_client.put("/api/containers/-/settings", json=settings).status_code == 200
    response = containers_client.post("/api/containers/shop-db-1/restart")
    assert (response.status_code, response.json()["code"]) == (403, "container_locked")
    locked = {
        c["name"]: c["locked"]
        for c in containers_client.get("/api/containers").json()["containers"]
    }
    assert locked["shop-db-1"] is True and locked["shop-web-1"] is False
    assert not [c for c in docker.calls if c[0] == "POST"]
    results = [
        i["result"] for i in containers_client.get("/api/containers/-/actions").json()["items"]
    ]
    assert results == ["container_locked", "container_locked"]


def test_read_only_mode_refuses_every_action(containers_client, docker):
    seed(docker)
    settings = containers_client.get("/api/containers/-/settings").json()
    settings["read_only"] = True
    containers_client.put("/api/containers/-/settings", json=settings)
    assert containers_client.get("/api/containers").json()["read_only"] is True
    response = containers_client.post("/api/containers/shop-web-1/restart")
    assert (response.status_code, response.json()["code"]) == (403, "containers_read_only")
    assert docker.containers["shop-web-1"].state == "running"


def test_hidden_containers_are_invisible(containers_client, docker):
    seed(docker)
    settings = containers_client.get("/api/containers/-/settings").json()
    settings["hidden"] = ["shop-*", " shop-* ", ""]
    saved = containers_client.put("/api/containers/-/settings", json=settings).json()
    assert saved["hidden"] == ["shop-*"]
    names = {c["name"] for c in containers_client.get("/api/containers").json()["containers"]}
    assert names == {"worker", "mysql-backup-panel-backend-1"}
    assert "shop-web-1" not in containers_client.get("/api/containers/-/stats").json()["stats"]
    assert containers_client.get("/api/containers/shop-web-1").status_code == 404
    assert containers_client.get("/api/containers/shop-web-1/logs").status_code == 404
    assert containers_client.post("/api/containers/shop-web-1/stop").status_code == 404
    assert docker.containers["shop-web-1"].state == "running"


def test_settings_validation(containers_client):
    defaults = containers_client.get("/api/containers/-/settings").json()
    assert defaults["bot_logs"] is False and defaults["monitor_all"] is True
    bad = {**defaults, "cpu_percent": 150}
    assert containers_client.put("/api/containers/-/settings", json=bad).status_code == 422
    bad = {**defaults, "unknown": 1}
    assert containers_client.put("/api/containers/-/settings", json=bad).status_code == 422


# --- the agent or Docker unavailable ---


def test_agent_not_installed(auth_client):
    # The default agent URL does not resolve in tests: as on a server without the agent.
    response = auth_client.get("/api/containers")
    assert (response.status_code, response.json()["code"]) == (503, "agent_unreachable")


def test_docker_unavailable_or_permission_denied(containers_client, docker):
    docker.down = True
    response = containers_client.get("/api/containers")
    assert (response.status_code, response.json()["code"]) == (503, "docker_unavailable")
    docker.down, docker.denied = False, True
    response = containers_client.get("/api/containers")
    assert (response.status_code, response.json()["code"]) == (503, "docker_permission_denied")


def test_wrong_agent_token_is_not_a_logout(auth_client, app, agent_app):
    from mbp.containers.agent_client import AgentClient

    previous = app.state.agent
    app.state.agent = AgentClient(
        "http://agent", "wrong", client=TestClient(agent_app, base_url="http://agent")
    )
    try:
        response = auth_client.get("/api/containers")
    finally:
        app.state.agent = previous
    assert (response.status_code, response.json()["code"]) == (502, "agent_unauthorized")


def test_audit_survives_failures(containers_client, docker, db):
    seed(docker)
    docker.down = True
    response = containers_client.post("/api/containers/shop-web-1/restart")
    assert response.status_code == 503
    entry = db.query(ContainerAction).one()
    assert (entry.result, entry.container) == ("docker_unavailable", "shop-web-1")
