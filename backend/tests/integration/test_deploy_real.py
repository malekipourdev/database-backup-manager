"""Deploy jobs with real git and docker compose (needs the Docker socket)."""

import os
import subprocess
import time
import uuid

import pytest

from mbp.agent.deploy import DeployManager, DeploySpec
from tests.integration.conftest import IMAGES

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.path.exists("/var/run/docker.sock"), reason="no Docker socket"),
]

# A tricky value: quotes, $, backslash, newline. Must reach the container unchanged.
VALUE = 'it\'s "quoted" $HOME \\path\nline2'
COMPOSE = """services:
  app:
    image: {image}
    entrypoint: ["sh", "-c", "{script}"]
    env_file: .env
"""
OK = "trap 'exit 0' TERM; while true; do sleep 1; done"
BROKEN = "sleep 1; exit 3"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, timeout=60)


def commit(repo, script, message):
    (repo / "docker-compose.yml").write_text(COMPOSE.format(image=IMAGES["mysql"], script=script))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("MBP_AGENT_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    name = f"it{uuid.uuid4().hex[:8]}"
    manager = DeployManager(
        tmp_path / "projects", git_protocols="https:ssh:file", sleep=lambda s: time.sleep(min(s, 2))
    )
    yield manager, repo, name
    docker("compose", "-p", name, "down", "--remove-orphans", "-t", "1")


def test_deploy_redeploy_rollback_remove(setup):
    manager, repo, name = setup
    good = commit(repo, OK, "good version")

    def deploy(ref):
        spec = DeploySpec(
            project=name,
            repo_url=f"file://{repo}",
            ref=ref,
            env={"APP_SECRET": VALUE, "MODE": "prod"},
        )
        return manager.start(spec, background=False)

    job = deploy("main")
    assert job.status == "success", job.lines
    assert job.commit_sha == good
    container = f"{name}-app-1"
    printed = docker("exec", container, "printenv", "APP_SECRET")
    assert printed.stdout == VALUE + "\n"
    assert "it's" not in "\n".join(job.lines)  # the value is masked in the log

    commit(repo, BROKEN, "broken version")
    job = deploy("main")
    assert (job.status, job.error_code) == ("failed", "service_failed"), job.lines
    assert "app: exited with code 3" in job.error_detail

    job = deploy(good)
    assert job.status == "success", job.lines
    assert manager.state(name)["commit_sha"] == good
    assert docker("inspect", "-f", "{{.State.Running}}", container).stdout.strip() == "true"

    assert manager.remove(name, "docker-compose.yml", down=True) == {"removed": True}
    assert docker("inspect", container).returncode != 0
    assert manager.state(name)["exists"] is False
