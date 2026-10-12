"""The agent's deploy jobs, with scripted commands (no git or Docker needed)."""

import base64

import pytest

from mbp.agent.deploy import DeployManager, DeploySpec, dotenv_line
from mbp.agent.docker import DockerError
from tests.fakes.fake_commands import FakeCommands

TOKEN = "ghp_Token-Value-12345"
KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "AAAAKeyMaterialLine1234\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


@pytest.fixture
def commands():
    return FakeCommands()


@pytest.fixture
def manager(tmp_path, commands, monkeypatch):
    monkeypatch.setenv("MBP_AGENT_HOME", str(tmp_path / "home"))
    return DeployManager(
        tmp_path / "projects",
        runner=commands,
        protected_projects=lambda: {"mysql-backup-panel"},
        sleep=lambda s: None,
    )


def spec(**overrides):
    values = {
        "project": "shop",
        "repo_url": "https://github.com/acme/shop.git",
        "ref": "main",
        "env": {"DB_PASSWORD": "Db-Secret-99", "MODE": "prod"},
    }
    values.update(overrides)
    return DeploySpec(**values)


def test_successful_deploy_runs_the_fixed_steps(manager, commands, tmp_path):
    job = manager.start(spec(), background=False)
    assert job.status == "success", job.lines
    assert commands.called() == [
        "git init",
        "git remote",
        "git fetch",
        "git checkout",
        "git log",
        "compose config",
        "compose pull",
        "compose build",
        "compose up",
        "compose ps",
    ]
    up = next(c for c in commands.calls if c["key"] == "compose up")
    assert up["args"] == [
        "docker",
        "compose",
        "-p",
        "shop",
        "-f",
        "docker-compose.yml",
        "up",
        "-d",
        "--remove-orphans",
    ]
    assert up["cwd"] == str(tmp_path / "projects" / "shop")
    assert (job.commit_sha, job.commit_message) == ("a" * 40, "Add feature")
    env_file = tmp_path / "projects" / "shop" / ".env"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    assert "DB_PASSWORD='Db-Secret-99'" in env_file.read_text()
    assert "Db-Secret-99" not in "\n".join(job.lines)
    # Only file:// and other local transports are not allowed.
    assert all(c["env"]["GIT_ALLOW_PROTOCOL"] == "https:ssh" for c in commands.calls)


def test_second_deploy_reuses_the_checkout(manager, commands):
    manager.start(spec(), background=False)
    commands.calls.clear()
    manager.start(spec(ref="0123456789abcdef0123456789abcdef01234567"), background=False)
    assert commands.called()[:2] == ["git remote", "git fetch"]
    fetch = next(c for c in commands.calls if c["key"] == "git fetch")
    assert fetch["args"][-1] == "0123456789abcdef0123456789abcdef01234567"


def test_token_never_on_the_command_line_and_masked(manager, commands):
    commands.output["git fetch"] = [f"remote: hello {TOKEN}"]
    job = manager.start(spec(auth_type="token", credential=TOKEN), background=False)
    assert job.status == "success"
    for call in commands.calls:
        assert TOKEN not in " ".join(call["args"])
    fetch = next(c for c in commands.calls if c["key"] == "git fetch")
    header = fetch["env"]["GIT_CONFIG_VALUE_1"]
    assert base64.b64decode(header.split()[-1]).decode() == f"x-access-token:{TOKEN}"
    assert TOKEN not in "\n".join(job.lines)
    assert "remote: hello ***" in job.lines


def test_ssh_key_is_used_from_a_private_file_then_removed(manager, commands, tmp_path):
    job = manager.start(
        spec(repo_url="git@github.com:acme/shop.git", auth_type="ssh_key", credential=KEY),
        background=False,
    )
    assert job.status == "success"
    fetch = next(c for c in commands.calls if c["key"] == "git fetch")
    ssh = fetch["env"]["GIT_SSH_COMMAND"]
    assert "-i " in ssh and "StrictHostKeyChecking=accept-new" in ssh and "BatchMode=yes" in ssh
    key_path = ssh.split("-i ")[1].split()[0]
    assert not (tmp_path / key_path).exists()
    assert not list((tmp_path / "home").iterdir())


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("project", "Shop", "invalid_project"),
        ("project", "../etc", "invalid_project"),
        ("repo_url", "file:///etc", "invalid_repo_url"),
        ("repo_url", "ext::sh -c touch% /tmp/pwned", "invalid_repo_url"),
        ("repo_url", "--upload-pack=touch /tmp/x", "invalid_repo_url"),
        ("ref", "--orphan", "invalid_ref"),
        ("ref", "main/../x", "invalid_ref"),
        ("compose_file", "../docker-compose.yml", "invalid_compose_file"),
        ("compose_file", "/etc/compose.yml", "invalid_compose_file"),
        ("compose_file", "compose.json", "invalid_compose_file"),
    ],
)
def test_invalid_input_is_refused(manager, commands, field, value, code):
    with pytest.raises(DockerError) as raised:
        manager.start(spec(**{field: value}), background=False)
    assert raised.value.code == code
    assert commands.calls == []


def test_bad_env_name_and_auth(manager):
    with pytest.raises(DockerError) as raised:
        manager.start(spec(env={"BAD-NAME": "x"}), background=False)
    assert raised.value.code == "invalid_env_name"
    with pytest.raises(DockerError) as raised:
        manager.start(spec(auth_type="token", credential=None), background=False)
    assert raised.value.code == "invalid_auth"


def test_the_panel_itself_cannot_be_deployed_over(manager, commands):
    with pytest.raises(DockerError) as raised:
        manager.start(spec(project="mysql-backup-panel"), background=False)
    assert (raised.value.status, raised.value.code) == (403, "project_protected")
    with pytest.raises(DockerError):
        manager.remove("mysql-backup-panel", "docker-compose.yml", down=True)
    assert commands.calls == []


@pytest.mark.parametrize(
    "key,code",
    [
        ("git fetch", "fetch_failed"),
        ("compose config", "compose_invalid"),
        ("compose build", "build_failed"),
        ("compose up", "up_failed"),
    ],
)
def test_failed_step_is_reported(manager, commands, key, code):
    commands.fail[key] = 1
    job = manager.start(spec(), background=False)
    assert (job.status, job.error_code, job.error_detail) == ("failed", code, "exit code 1")
    assert job.lines[-1].startswith(f"✖ {code}")


def test_pull_failure_is_not_fatal(manager, commands):
    commands.fail["compose pull"] = 1
    job = manager.start(spec(), background=False)
    assert job.status == "success"
    assert any("Pulling images failed" in line for line in job.lines)


def test_service_that_exits_fails_the_deploy(manager, commands):
    commands.ps = [
        {"Service": "web", "State": "running", "Health": "healthy", "ExitCode": 0},
        {"Service": "migrate", "State": "exited", "Health": "", "ExitCode": 0},
        {"Service": "worker", "State": "exited", "Health": "", "ExitCode": 2},
    ]
    job = manager.start(spec(), background=False)
    assert (job.status, job.error_code) == ("failed", "service_failed")
    assert job.error_detail == "worker: exited with code 2"


def test_one_deploy_per_project_at_a_time(manager, commands):
    import threading

    commands.gate = threading.Event()
    first = manager.start(spec(), background=True)
    with pytest.raises(DockerError) as raised:
        manager.start(spec(), background=True)
    assert raised.value.code == "deploy_in_progress"
    commands.gate.set()
    for _ in range(200):
        if manager.get(first.id).status != "running":
            break
        import time

        time.sleep(0.02)
    assert manager.get(first.id).status == "success"


def test_job_view_offsets(manager):
    job = manager.start(spec(), background=False)
    full = job.view(0)
    assert full["next_offset"] == len(full["lines"])
    assert job.view(full["next_offset"])["lines"] == []
    assert job.view(2)["lines"] == full["lines"][2:]


def test_env_file_removed_when_variables_are_cleared(manager, tmp_path):
    manager.start(spec(), background=False)
    env_file = tmp_path / "projects" / "shop" / ".env"
    assert env_file.exists()
    manager.start(spec(env={}), background=False)
    assert not env_file.exists()


def test_remove_runs_down_and_deletes_the_checkout(manager, commands, tmp_path):
    manager.start(spec(), background=False)
    commands.calls.clear()
    assert manager.remove("shop", "docker-compose.yml", down=True) == {"removed": True}
    assert commands.calls[0]["args"][:4] == ["docker", "compose", "-p", "shop"]
    assert commands.calls[0]["args"][-2:] == ["down", "--remove-orphans"]
    assert not (tmp_path / "projects" / "shop").exists()


def test_state(manager):
    assert manager.state("shop")["exists"] is False
    manager.start(spec(), background=False)
    assert manager.state("shop") == {
        "exists": True,
        "commit_sha": "a" * 40,
        "commit_message": "Add feature",
    }


@pytest.mark.parametrize(
    "value",
    ["plain", "with 'quote'", 'dq " and $HOME and \\', "multi\nline", ""],
)
def test_dotenv_line_shapes(value):
    line = dotenv_line("X", value)
    assert line.startswith("X=") and line.endswith("\n") and line.count("\n") == 1


def test_state_while_the_first_fetch_has_no_commit(manager, commands, tmp_path):
    (tmp_path / "projects" / "shop" / ".git").mkdir(parents=True)
    commands.commit = ("fatal: your current branch 'master' does not have any commits yet", "")
    commands.fail["git log"] = 128
    assert manager.state("shop") == {"exists": True, "commit_sha": None, "commit_message": None}
