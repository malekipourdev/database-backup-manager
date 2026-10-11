"""The Docker agent against the real Docker Engine (needs /var/run/docker.sock)."""

import json
import os
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from mbp.agent.app import AgentSettings, create_agent_app
from mbp.security.agent_token import agent_token
from tests.conftest import TEST_ENCRYPTION_KEY
from tests.integration.conftest import IMAGES

SOCKET = "/var/run/docker.sock"
SECRET = "Real-Secret-Value-9"
# sh as PID 1 ignores SIGTERM unless it traps it.
LOOP = (
    "trap 'exit 0' TERM; i=0; while true; do echo out $i; echo err $i >&2; "
    "i=$((i+1)); sleep 1 & wait $!; done"
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.path.exists(SOCKET), reason="no Docker socket"),
]


def docker(*args: str) -> str:
    return subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


@pytest.fixture
def containers():
    names: list[str] = []

    def run(*extra: str, labels: dict | None = None) -> str:
        name = f"mbp-it-{uuid.uuid4().hex[:8]}"
        args = ["run", "-d", "--name", name, "-e", f"APP_PASSWORD={SECRET}"]
        for key, value in (labels or {}).items():
            args += ["--label", f"{key}={value}"]
        args += [*extra, "--entrypoint", "sh", IMAGES["mysql"], "-c", LOOP]
        docker(*args)
        names.append(name)
        return name

    yield run
    if names:
        subprocess.run(["docker", "rm", "-f", *names], capture_output=True, timeout=120)


@pytest.fixture
def agent():
    app = create_agent_app(AgentSettings(encryption_key=TEST_ENCRYPTION_KEY))
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {agent_token(TEST_ENCRYPTION_KEY)}"
    return client


def wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.5)
    raise AssertionError("timed out")


def test_list_details_logs_stats(agent, containers):
    name = containers(
        "--health-cmd",
        "exit 1",
        "--health-interval",
        "1s",
        "--health-retries",
        "1",
        labels={"com.docker.compose.project": "itest", "com.docker.compose.service": "app"},
    )
    listed = {c["name"]: c for c in agent.get("/v1/containers").json()["containers"]}
    item = listed[name]
    assert (item["state"], item["project"], item["service"]) == ("running", "itest", "app")

    def unhealthy():
        return agent.get(f"/v1/containers/{name}").json()["health"] == "unhealthy"

    wait_for(unhealthy)
    details = agent.get(f"/v1/containers/{name}")
    assert "APP_PASSWORD" in details.json()["env_names"]
    assert SECRET not in details.text
    assert details.json()["health_failing_streak"] >= 1

    wait_for(lambda: len(agent.get(f"/v1/containers/{name}/logs?tail=10").json()["lines"]) >= 4)
    lines = agent.get(f"/v1/containers/{name}/logs?tail=10").json()["lines"]
    streams = {line["stream"] for line in lines}
    assert streams == {"stdout", "stderr"}
    assert all(line["time"] for line in lines)
    assert any(line["text"].startswith("err ") and line["stream"] == "stderr" for line in lines)

    first = agent.get(f"/v1/containers/{name}/stats").json()["stats"]
    assert first["memory_usage"] > 0 and first["pids"] >= 1
    time.sleep(1)
    second = agent.get(f"/v1/containers/{name}/stats").json()["stats"]
    assert second["cpu_percent"] is not None

    info = agent.get("/v1/info").json()
    assert info["docker"]["version"]
    assert info["host"]["memory_total"] > 0 and info["host"]["disk_total"] > 0


def test_stop_start_restart(agent, containers):
    name = containers()
    stopped = agent.post(f"/v1/containers/{name}/stop").json()["container"]
    assert stopped["state"] == "exited" and stopped["exit_code"] == 0
    # Stopping again is not an error.
    assert agent.post(f"/v1/containers/{name}/stop").status_code == 200
    assert agent.post(f"/v1/containers/{name}/start").json()["container"]["state"] == "running"
    restarted = agent.post(f"/v1/containers/{name}/restart").json()["container"]
    assert restarted["state"] == "running"
    state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
    assert state["Running"] is True


def test_panel_containers_are_refused(agent, containers):
    name = containers(labels={"mbp.role": "panel"})
    response = agent.post(f"/v1/containers/{name}/stop")
    assert (response.status_code, response.json()["code"]) == (403, "container_protected")
    assert json.loads(docker("inspect", "--format", "{{json .State}}", name))["Running"] is True


def test_unknown_container_and_bad_names(agent):
    assert agent.get("/v1/containers/does-not-exist-123").status_code == 404
    assert agent.get("/v1/containers/..%2F..%2Fimages/logs").status_code == 404
    assert agent.post("/v1/containers/x/kill").status_code in (400, 404)
