"""Projects: registration, secrets, deploys through the agent, pre-deploy backups, alerts."""

import time

import pytest

from mbp.db import get_sessionmaker
from mbp.models import BackupRun, Deployment, NotificationLog
from tests.conftest import create_instance

TOKEN = "ghp_Project-Token-777"
SECRET = "Env-Secret-Value-55"


def body(**overrides):
    data = {
        "name": "shop",
        "repo_url": "https://github.com/acme/shop.git",
        "branch": "main",
        "compose_file": "docker-compose.yml",
        "auth_type": "token",
        "credential": TOKEN,
        "env": [{"name": "DB_PASSWORD", "value": SECRET}, {"name": "MODE", "value": "prod"}],
    }
    data.update(overrides)
    return data


def create(client, **overrides):
    response = client.post("/api/projects", json=body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def wait_deploy(client, deployment_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = client.get(f"/api/deployments/{deployment_id}").json()
        if d["status"] in ("success", "failed"):
            return d
        time.sleep(0.05)
    raise AssertionError("deploy did not finish")


def deploy(client, project_id, **payload):
    response = client.post(f"/api/projects/{project_id}/deploy", json=payload)
    assert response.status_code == 202, response.text
    return wait_deploy(client, response.json()["id"])


# --- registration ---


def test_create_never_returns_secrets(auth_client):
    response = auth_client.post("/api/projects", json=body())
    assert response.status_code == 201
    project = response.json()
    assert project["has_credential"] is True
    assert project["env_names"] == ["DB_PASSWORD", "MODE"]
    assert project["last_deployment"] is None
    for text in (response.text, auth_client.get("/api/projects").text):
        assert TOKEN not in text and SECRET not in text


@pytest.mark.parametrize(
    "overrides,field,code",
    [
        ({"name": "Shop"}, "name", "invalid_project_name"),
        ({"name": "mysql-backup-panel"}, "name", "invalid_project_name"),
        ({"repo_url": "file:///etc"}, "repo_url", "invalid_repo_url"),
        ({"branch": "--force"}, "branch", "invalid_ref"),
        ({"compose_file": "../x.yml"}, "compose_file", "invalid_compose_file"),
        ({"credential": None}, "credential", "required"),
        ({"backup_instance_id": 999}, "backup_instance_id", "instance_not_found"),
    ],
)
def test_validation(auth_client, overrides, field, code):
    response = auth_client.post("/api/projects", json=body(**overrides))
    assert response.status_code == 422
    assert response.json()["fields"][field] == code


def test_bad_env(auth_client):
    response = auth_client.post(
        "/api/projects", json=body(env=[{"name": "BAD-NAME", "value": "x"}])
    )
    assert response.json()["fields"] == {"env": "invalid_env_name"}
    dup = [{"name": "A", "value": "1"}, {"name": "A", "value": "2"}]
    assert auth_client.post("/api/projects", json=body(env=dup)).json()["fields"] == {
        "env": "duplicate_env_name"
    }
    missing = [{"name": "A", "value": None}]
    assert auth_client.post("/api/projects", json=body(env=missing)).json()["fields"] == {
        "env": "env_value_required"
    }


def test_names_are_unique(auth_client):
    create(auth_client)
    response = auth_client.post("/api/projects", json=body())
    assert response.json()["fields"] == {"name": "name_taken"}


def test_update_keeps_changes_and_removes_variables(containers_client, agent_commands, tmp_path):
    project = create(containers_client)
    update = body(
        credential=None,
        env=[{"name": "DB_PASSWORD", "value": None}, {"name": "NEW", "value": "n"}],
    )
    response = containers_client.put(f"/api/projects/{project['id']}", json=update)
    assert response.status_code == 200, response.text
    assert response.json()["env_names"] == ["DB_PASSWORD", "NEW"]
    assert response.json()["has_credential"] is True
    deploy(containers_client, project["id"])
    env_file = (tmp_path / "projects" / "shop" / ".env").read_text()
    assert f"DB_PASSWORD='{SECRET}'" in env_file and "NEW='n'" in env_file
    assert "MODE" not in env_file
    cleared = containers_client.put(
        f"/api/projects/{project['id']}",
        json=body(auth_type="none", credential=None, env=[]),
    ).json()
    assert cleared["has_credential"] is False and cleared["env_names"] == []


# --- deploys ---


def test_deploy_success(containers_client, agent_commands, db):
    project = create(containers_client)
    result = deploy(containers_client, project["id"])
    assert result["status"] == "success", result["log"]
    assert (result["commit_sha"], result["commit_message"]) == ("a" * 40, "Add feature")
    assert (result["trigger"], result["actor"], result["ref"]) == ("panel", "admin", "main")
    assert "compose up" not in result["log"]  # the agent logs the real command line
    assert "docker compose -p shop -f docker-compose.yml up -d --remove-orphans" in result["log"]
    assert "✔ Deployed." in result["log"]
    assert SECRET not in result["log"] and TOKEN not in result["log"]
    # The token reached git only through the environment.
    fetch = next(c for c in agent_commands.calls if c["key"] == "git fetch")
    assert TOKEN not in " ".join(fetch["args"])
    listed = containers_client.get("/api/projects").json()[0]
    assert listed["last_deployment"]["status"] == "success"
    assert listed["last_success"]["id"] == result["id"]
    alert = db.query(NotificationLog).filter_by(event="deploy_succeeded").one()
    assert alert.params["project"] == "shop" and alert.params["commit"] == "aaaaaaaa"
    state = containers_client.get(f"/api/projects/{project['id']}/state").json()
    assert state == {
        "available": True,
        "error_code": None,
        "exists": True,
        "commit_sha": "a" * 40,
        "commit_message": "Add feature",
        "path": state["path"],
    }
    assert state["path"].endswith("/projects/shop")


def test_deploy_failure_is_reported_and_alerted(containers_client, agent_commands, db):
    agent_commands.fail["compose build"] = 1
    project = create(containers_client)
    result = deploy(containers_client, project["id"])
    assert (result["status"], result["error_code"], result["step"]) == (
        "failed",
        "build_failed",
        "build",
    )
    alert = db.query(NotificationLog).filter_by(event="deploy_failed").one()
    assert alert.severity == "error" and alert.params["error"] == "build_failed"
    # The failure is written once (by the agent), not repeated by the panel.
    assert result["log"].count("✖ build_failed") == 1


def test_redeploy_a_version(containers_client, agent_commands):
    project = create(containers_client)
    sha = "0123456789abcdef0123456789abcdef01234567"
    result = deploy(containers_client, project["id"], ref=sha)
    assert result["ref"] == sha
    fetch = next(c for c in agent_commands.calls if c["key"] == "git fetch")
    assert fetch["args"][-1] == sha
    bad = containers_client.post(f"/api/projects/{project['id']}/deploy", json={"ref": "-x"})
    assert bad.status_code == 422


def test_one_deploy_at_a_time(containers_client, agent_commands):
    import threading

    agent_commands.gate = threading.Event()
    project = create(containers_client)
    first = containers_client.post(f"/api/projects/{project['id']}/deploy", json={})
    assert first.status_code == 202
    second = containers_client.post(f"/api/projects/{project['id']}/deploy", json={})
    assert (second.status_code, second.json()["code"]) == (409, "deploy_in_progress")
    delete = containers_client.delete(f"/api/projects/{project['id']}")
    assert delete.status_code == 409
    agent_commands.gate.set()
    assert wait_deploy(containers_client, first.json()["id"])["status"] == "success"


def test_pre_deploy_backup(containers_client, agent_commands, probe_ok, db):
    instance_id = create_instance(containers_client)
    project = create(
        containers_client, backup_instance_id=instance_id, backup_databases=["shop", "users"]
    )
    result = deploy(containers_client, project["id"])
    assert result["status"] == "success", result["log"]
    assert len(result["backup_run_ids"]) == 2
    runs = db.query(BackupRun).all()
    assert {(r.database_name, r.trigger, r.status) for r in runs} == {
        ("shop", "deploy", "success"),
        ("users", "deploy", "success"),
    }
    assert "Backup done." in result["log"]


def test_failed_backup_stops_the_deploy(containers_client, agent_commands, probe_ok):
    instance_id = create_instance(containers_client)
    project = create(
        containers_client, backup_instance_id=instance_id, backup_databases=["denied_shop"]
    )
    result = deploy(containers_client, project["id"])
    assert (result["status"], result["error_code"], result["step"]) == (
        "failed",
        "backup_failed",
        "backup",
    )
    assert "compose up" not in agent_commands.called()
    # Not required: the deploy goes on.
    containers_client.put(
        f"/api/projects/{project['id']}",
        json=body(
            credential=None,
            env=[{"name": "DB_PASSWORD", "value": None}, {"name": "MODE", "value": None}],
            backup_instance_id=instance_id,
            backup_databases=["denied_shop"],
            backup_required=False,
        ),
    )
    result = deploy(containers_client, project["id"])
    assert result["status"] == "success"
    assert "Backup problems" in result["log"]


def test_agent_missing(auth_client):
    project = create(auth_client)
    result = deploy(auth_client, project["id"])
    assert (result["status"], result["error_code"]) == ("failed", "agent_unreachable")
    state = auth_client.get(f"/api/projects/{project['id']}/state").json()
    assert state["available"] is False and state["error_code"] == "agent_unreachable"


def test_interrupted_deploys_are_failed_on_start(app):
    with get_sessionmaker()() as session:
        session.add(
            Deployment(
                project_name="x",
                trigger="panel",
                actor="a",
                ref="main",
                status="running",
                log="",
                backup_run_ids=[],
            )
        )
        session.commit()
    assert app.state.deploy_runner.recover() == 1
    with get_sessionmaker()() as session:
        d = session.query(Deployment).one()
        assert (d.status, d.error_code) == ("failed", "interrupted")


def test_delete(containers_client, agent_commands, tmp_path):
    never = create(containers_client, name="never")
    assert containers_client.delete(f"/api/projects/{never['id']}?down=true").status_code == 204
    assert agent_commands.calls == []  # never deployed: nothing on the server

    project = create(containers_client)
    deployed = deploy(containers_client, project["id"])
    agent_commands.calls.clear()
    assert containers_client.delete(f"/api/projects/{project['id']}?down=true").status_code == 204
    assert agent_commands.calls[0]["args"][-2:] == ["down", "--remove-orphans"]
    assert not (tmp_path / "projects" / "shop").exists()
    assert containers_client.get(f"/api/projects/{project['id']}").status_code == 404
    # The history is kept, with the project's name.
    kept = containers_client.get(f"/api/deployments/{deployed['id']}").json()
    assert kept["project_id"] is None and kept["project_name"] == "shop"


def test_rename_after_deploy_is_refused(containers_client):
    project = create(containers_client)
    deploy(containers_client, project["id"])
    renamed = containers_client.put(
        f"/api/projects/{project['id']}", json=body(name="shop2", credential=None, env=[])
    )
    assert renamed.json()["fields"] == {"name": "rename_after_deploy"}


def test_log_offsets_and_history(containers_client):
    project = create(containers_client)
    result = deploy(containers_client, project["id"])
    size = result["log_size"]
    tail = containers_client.get(f"/api/deployments/{result['id']}?offset={size - 12}").json()
    assert tail["log"] == result["log"][-12:]
    page = containers_client.get(f"/api/projects/{project['id']}/deployments").json()
    assert page["total"] == 1 and page["items"][0]["id"] == result["id"]
    assert containers_client.get("/api/deployments/999").status_code == 404


@pytest.mark.parametrize("lang", ["fa", "en"])
def test_deploy_alert_texts(lang):
    from zoneinfo import ZoneInfo

    from mbp.notifications.events import Event
    from mbp.notifications.render import render

    base = {"project": "shop", "commit": "aaaaaaaa", "message": "Add feature", "actor": "admin"}
    ok = render(Event("deploy_succeeded", "s", base), lang, ZoneInfo("UTC"))
    assert "shop" in ok and "aaaaaaaa" in ok
    for error in ("build_failed", "service_failed", "some_new_code"):
        failed = Event("deploy_failed", "s", {**base, "error": error, "detail": "web: exited"})
        text = render(failed, lang, ZoneInfo("UTC"))
        assert "result_" not in text and "{" not in text and "web: exited" in text


def test_folders(auth_client):
    first = create(auth_client, name="api", folder="  Airplus   Core ")
    assert first["folder"] == "Airplus Core"
    second = create(auth_client, name="web", folder="Airplus Core")
    plain = create(auth_client, name="blog")
    assert plain["folder"] is None
    listed = {p["name"]: p["folder"] for p in auth_client.get("/api/projects").json()}
    assert listed == {"api": "Airplus Core", "web": "Airplus Core", "blog": None}
    moved = auth_client.put(
        f"/api/projects/{second['id']}",
        json={**body(name="web", credential=None), "folder": "ایرپلاس"},
    )
    assert moved.status_code == 200 and moved.json()["folder"] == "ایرپلاس"
    cleared = auth_client.put(
        f"/api/projects/{second['id']}", json={**body(name="web", credential=None), "folder": ""}
    )
    assert cleared.json()["folder"] is None
    for bad in ("a/b", "nul\x00here", "x" * 61):
        response = auth_client.post("/api/projects", json=body(name="bad", folder=bad))
        assert response.status_code == 422, bad


def test_deploy_into_the_projects_folder(containers_client, agent_commands, monkeypatch):
    project = create(containers_client, name="api", folder="Airplus")
    done = deploy(containers_client, project["id"])
    assert done["status"] == "success", done
    up = next(c for c in agent_commands.calls if c["key"] == "compose up")
    assert up["cwd"].endswith("/projects/Airplus/api")
    state = containers_client.get(f"/api/projects/{project['id']}/state").json()
    assert state["path"].endswith("/projects/Airplus/api")

    # An agent from before folders would deploy elsewhere: refused instead.
    from mbp.containers.agent_client import AgentClient

    monkeypatch.setattr(AgentClient, "capabilities", lambda self: {"deploy_modes": ["deploy"]})
    refused = deploy(containers_client, project["id"])
    assert (refused["status"], refused["error_code"]) == ("failed", "agent_outdated")
