"""Deploy jobs: fetch a project's git repository and run it with docker compose.

Only fixed commands run, always as argument lists (never through a shell), inside the
project's own directory under the projects root: git (init, remote, fetch, checkout, log) and
docker compose (config, pull, build, up, ps, down). Credentials reach git through the
environment, never the command line, and every secret is masked in the job log.
"""

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from mbp.agent.docker import DockerError

logger = logging.getLogger(__name__)

PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
# Branch, tag or commit; no option-looking or parent-directory values.
GIT_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")
COMPOSE_FILE_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9._-]*/)*[A-Za-z0-9_][A-Za-z0-9._-]*\.ya?ml")
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
REPO_URL_RE = re.compile(
    r"(https://[^\s@/]+(:\d+)?/\S+|ssh://[^\s/]+/\S+|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:\S+)"
)
AUTH_TYPES = ("none", "token", "ssh_key")
ENV_MARKER = "# Written by MySQL Backup Panel on every deploy; edit the variables in the panel.\n"
MASK = "***"
MAX_LOG_LINES = 20000
MAX_LINE_CHARS = 2000
STEP_TIMEOUTS = {"fetch": 300, "config": 120, "pull": 1800, "build": 3600, "up": 900}
CHECK_SECONDS = 60
SETTLE_SECONDS = 8
JOB_TTL_SECONDS = 24 * 3600


def valid_project(name: str) -> bool:
    return bool(PROJECT_RE.fullmatch(name))


def valid_ref(ref: str) -> bool:
    return bool(GIT_REF_RE.fullmatch(ref)) and ".." not in ref and not ref.endswith((".lock", "/"))


def valid_compose_file(path: str) -> bool:
    return bool(COMPOSE_FILE_RE.fullmatch(path)) and ".." not in path.split("/")


def valid_repo_url(url: str) -> bool:
    return bool(REPO_URL_RE.fullmatch(url)) and not url.startswith("-")


def dotenv_line(name: str, value: str) -> str:
    """One .env line that docker compose reads back as exactly `value` (tested)."""
    if "'" not in value and "\n" not in value and "\r" not in value:
        return f"{name}='{value}'\n"
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'{name}="{escaped}"\n'


@dataclass
class DeploySpec:
    project: str
    repo_url: str
    ref: str
    compose_file: str = "docker-compose.yml"
    env: dict[str, str] = field(default_factory=dict)
    auth_type: str = "none"
    credential: str | None = None

    def validate(self, allow_file: bool = False) -> None:
        if not valid_project(self.project):
            raise DockerError("invalid_project", 422)
        local = allow_file and self.repo_url.startswith("file:///")
        if not local and not valid_repo_url(self.repo_url):
            raise DockerError("invalid_repo_url", 422)
        if not valid_ref(self.ref):
            raise DockerError("invalid_ref", 422)
        if not valid_compose_file(self.compose_file):
            raise DockerError("invalid_compose_file", 422)
        if self.auth_type not in AUTH_TYPES or (self.auth_type != "none" and not self.credential):
            raise DockerError("invalid_auth", 422)
        for name in self.env:
            if not ENV_NAME_RE.fullmatch(name):
                raise DockerError("invalid_env_name", 422, name[:64])

    def secrets(self) -> list[str]:
        values = [v for v in self.env.values() if len(v) >= 4]
        if self.credential:
            values.append(self.credential)
            values.extend(line for line in self.credential.splitlines() if len(line) >= 8)
        return values


@dataclass
class Job:
    id: str
    project: str
    status: str = "running"  # running | success | failed
    step: str = "fetch"
    lines: list[str] = field(default_factory=list)
    dropped: int = 0
    commit_sha: str | None = None
    commit_message: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None

    def view(self, offset: int) -> dict:
        start = max(offset - self.dropped, 0)
        return {
            "job_id": self.id,
            "project": self.project,
            "status": self.status,
            "step": self.step,
            "lines": self.lines[start:],
            "next_offset": self.dropped + len(self.lines),
            "commit_sha": self.commit_sha,
            "commit_message": self.commit_message,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
        }


class StepFailed(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


class CommandRunner:
    """Runs one command, streaming its merged output line by line."""

    def run(
        self,
        args: list[str],
        cwd: Path,
        env: dict[str, str],
        timeout: float,
        on_line: Callable[[str], None],
    ) -> int:
        process = subprocess.Popen(  # noqa: S603 - fixed commands, argument lists, no shell
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        timed_out = threading.Event()

        def kill() -> None:
            timed_out.set()
            process.kill()

        timer = threading.Timer(timeout, kill)
        timer.start()
        try:
            for line in process.stdout or ():
                on_line(line.rstrip("\n"))
            code = process.wait()
        finally:
            timer.cancel()
        return 124 if timed_out.is_set() else code


class DeployManager:
    def __init__(
        self,
        projects_root: str | Path,
        *,
        runner: CommandRunner | None = None,
        protected_projects: Callable[[], set[str]] = lambda: set(),
        git_protocols: str = "https:ssh",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.root = Path(projects_root)
        self.runner = runner or CommandRunner()
        self.protected_projects = protected_projects
        self.git_protocols = git_protocols
        self.sleep = sleep
        self._jobs: dict[str, Job] = {}
        self._busy: set[str] = set()
        self._lock = threading.Lock()

    # --- jobs ---

    def start(self, spec: DeploySpec, *, background: bool = True) -> Job:
        # file:// only when explicitly allowed (tests); never in the default configuration.
        spec.validate(allow_file="file" in self.git_protocols.split(":"))
        if spec.project in self.protected_projects():
            raise DockerError("project_protected", 403)
        with self._lock:
            self._expire()
            if spec.project in self._busy:
                raise DockerError("deploy_in_progress", 409)
            self._busy.add(spec.project)
            job = Job(id=uuid.uuid4().hex, project=spec.project)
            self._jobs[job.id] = job
        if background:
            threading.Thread(target=self._run, args=(job, spec), daemon=True).start()
        else:
            self._run(job, spec)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _expire(self) -> None:
        now = time.monotonic()
        for key, job in list(self._jobs.items()):
            if job.finished is not None and now - job.finished > JOB_TTL_SECONDS:
                del self._jobs[key]

    # --- running ---

    def _project_dir(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if path.parent != self.root.resolve():
            raise DockerError("invalid_project", 422)
        return path

    def _log(self, job: Job, secrets: list[str], line: str) -> None:
        for secret in sorted(secrets, key=len, reverse=True):
            line = line.replace(secret, MASK)
        line = line[:MAX_LINE_CHARS]
        with self._lock:
            job.lines.append(line)
            if len(job.lines) > MAX_LOG_LINES:
                drop = len(job.lines) - MAX_LOG_LINES
                del job.lines[:drop]
                job.dropped += drop

    def _env(self, spec: DeploySpec, home: Path, key_file: Path | None) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            # No file://, ext:: or other local transports.
            "GIT_ALLOW_PROTOCOL": self.git_protocols,
            "DOCKER_CLI_HINTS": "false",
            "COMPOSE_PROGRESS": "plain",
            "BUILDKIT_PROGRESS": "plain",
        }
        if os.environ.get("DOCKER_HOST"):
            env["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
        # Configuration through the environment, never on a command line. The project
        # directories may belong to another user on the host: trust them explicitly.
        config = [("safe.directory", "*")]
        if spec.auth_type == "token" and spec.credential:
            basic = base64.b64encode(f"x-access-token:{spec.credential}".encode()).decode()
            config.append(("http.extraHeader", f"Authorization: Basic {basic}"))
        env["GIT_CONFIG_COUNT"] = str(len(config))
        for index, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        known_hosts = self.root / ".known_hosts"
        ssh = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={known_hosts}",
        ]
        if key_file is not None:
            ssh += ["-o", "IdentitiesOnly=yes", "-i", str(key_file)]
        env["GIT_SSH_COMMAND"] = " ".join(ssh)
        return env

    def _cmd(
        self,
        job: Job,
        spec: DeploySpec,
        step: str,
        args: list[str],
        cwd: Path,
        env: dict[str, str],
        *,
        error: str,
        capture: list[str] | None = None,
        quiet: bool = False,
    ) -> int:
        secrets = spec.secrets()
        if not quiet:
            self._log(job, secrets, f"$ {' '.join(args)}")

        def on_line(line: str) -> None:
            if capture is not None:
                capture.append(line)
            if not quiet:
                self._log(job, secrets, line)

        code = self.runner.run(args, cwd, env, STEP_TIMEOUTS.get(step, 600), on_line)
        if code != 0 and error:
            detail = "timeout" if code == 124 else f"exit code {code}"
            raise StepFailed(error, detail)
        return code

    def _step(self, job: Job, step: str) -> None:
        with self._lock:
            job.step = step

    def _run(self, job: Job, spec: DeploySpec) -> None:
        secrets = spec.secrets()
        home = Path(os.environ.get("MBP_AGENT_HOME", "/tmp/mbp-agent")) / job.id  # noqa: S108
        key_file: Path | None = None
        try:
            home.mkdir(parents=True, mode=0o700)
            if spec.auth_type == "ssh_key" and spec.credential:
                key_file = home / "deploy_key"
                key_file.write_text(spec.credential.strip() + "\n")
                key_file.chmod(0o600)
            env = self._env(spec, home, key_file)
            try:
                self.root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise StepFailed("projects_dir_not_writable", str(self.root)) from exc
            if not os.access(self.root, os.W_OK):
                raise StepFailed("projects_dir_not_writable", str(self.root))
            workdir = self._project_dir(spec.project)
            self._fetch(job, spec, workdir, env)
            self._write_env(job, spec, workdir)
            compose = ["docker", "compose", "-p", spec.project, "-f", spec.compose_file]
            self._step(job, "build")
            self._cmd(
                job,
                spec,
                "config",
                [*compose, "config", "--quiet"],
                workdir,
                env,
                error="compose_invalid",
            )
            code = self._cmd(
                job, spec, "pull", [*compose, "pull", "--ignore-buildable"], workdir, env, error=""
            )
            if code != 0:
                self._log(
                    job, secrets, "Pulling images failed; using the images already on the server."
                )
            self._cmd(job, spec, "build", [*compose, "build"], workdir, env, error="build_failed")
            self._step(job, "up")
            self._cmd(
                job,
                spec,
                "up",
                [*compose, "up", "-d", "--remove-orphans"],
                workdir,
                env,
                error="up_failed",
            )
            self._step(job, "check")
            self._check(job, spec, compose, workdir, env)
            self._finish(job, "success")
        except StepFailed as exc:
            self._log(job, secrets, f"✖ {exc.code}" + (f": {exc.detail}" if exc.detail else ""))
            self._finish(job, "failed", exc.code, exc.detail)
        except DockerError as exc:
            self._finish(job, "failed", exc.code, exc.message or None)
        except Exception as exc:  # never leave a job running
            logger.exception("Deploy of %s failed", spec.project)
            self._finish(job, "failed", "agent_error", type(exc).__name__)
        finally:
            shutil.rmtree(home, ignore_errors=True)
            with self._lock:
                self._busy.discard(spec.project)

    def _finish(
        self, job: Job, status: str, code: str | None = None, detail: str | None = None
    ) -> None:
        with self._lock:
            job.status, job.error_code, job.error_detail = status, code, detail
            job.finished = time.monotonic()

    def _fetch(self, job: Job, spec: DeploySpec, workdir: Path, env: dict[str, str]) -> None:
        self._step(job, "fetch")
        workdir.mkdir(exist_ok=True)
        if not (workdir / ".git").exists():
            self._cmd(
                job, spec, "fetch", ["git", "init", "--quiet"], workdir, env, error="fetch_failed"
            )
            self._cmd(
                job,
                spec,
                "fetch",
                ["git", "remote", "add", "origin", spec.repo_url],
                workdir,
                env,
                error="fetch_failed",
            )
        else:
            self._cmd(
                job,
                spec,
                "fetch",
                ["git", "remote", "set-url", "origin", spec.repo_url],
                workdir,
                env,
                error="fetch_failed",
            )
        self._cmd(
            job,
            spec,
            "fetch",
            ["git", "fetch", "--depth", "1", "--no-tags", "origin", spec.ref],
            workdir,
            env,
            error="fetch_failed",
        )
        # Tracked files are reset to the fetched commit; untracked ones (data directories,
        # the panel's .env) are left alone.
        self._cmd(
            job,
            spec,
            "fetch",
            ["git", "checkout", "--force", "--detach", "FETCH_HEAD"],
            workdir,
            env,
            error="fetch_failed",
        )
        out: list[str] = []
        self._cmd(
            job,
            spec,
            "fetch",
            ["git", "log", "-1", "--format=%H%n%s"],
            workdir,
            env,
            error="fetch_failed",
            capture=out,
            quiet=True,
        )
        with self._lock:
            job.commit_sha = out[0].strip() if out else None
            job.commit_message = out[1].strip()[:200] if len(out) > 1 else None
        self._log(job, spec.secrets(), f"→ commit {job.commit_sha}: {job.commit_message or ''}")

    def _write_env(self, job: Job, spec: DeploySpec, workdir: Path) -> None:
        target = (workdir / spec.compose_file).parent / ".env"
        if spec.env:
            content = ENV_MARKER + "".join(dotenv_line(k, v) for k, v in spec.env.items())
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(content)
            target.chmod(0o600)
            self._log(job, [], f"→ wrote {len(spec.env)} variable(s) to .env (values hidden)")
        elif target.exists() and target.read_text(errors="replace").startswith(ENV_MARKER):
            target.unlink()  # every variable was removed in the panel

    def _check(
        self, job: Job, spec: DeploySpec, compose: list[str], workdir: Path, env: dict[str, str]
    ) -> None:
        """Let the services settle; fail if one exits with an error, loops or is unhealthy."""
        deadline = time.monotonic() + CHECK_SECONDS
        self.sleep(SETTLE_SECONDS)
        problems: list[str] = []
        while True:
            out: list[str] = []
            self._cmd(
                job,
                spec,
                "config",
                [*compose, "ps", "-a", "--format", "json"],
                workdir,
                env,
                error="check_failed",
                capture=out,
                quiet=True,
            )
            services = _parse_ps(out)
            problems = [f"{s['name']}: {s['why']}" for s in services if s["why"] is not None]
            starting = any(s["health"] == "starting" for s in services)
            if problems or not starting or time.monotonic() > deadline:
                break
            self.sleep(3)
        for service in services:
            self._log(
                job,
                [],
                f"  {service['name']}: {service['state']}"
                + (f" ({service['health']})" if service["health"] else ""),
            )
        if problems:
            raise StepFailed("service_failed", "; ".join(problems)[:300])

    # --- other operations ---

    def state(self, name: str) -> dict:
        if not valid_project(name):
            raise DockerError("invalid_project", 422)
        workdir = self._project_dir(name)
        if not (workdir / ".git").exists():
            return {"exists": False, "commit_sha": None, "commit_message": None}
        out: list[str] = []
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": "/tmp",  # noqa: S108
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        }
        code = self.runner.run(
            ["git", "log", "-1", "--format=%H%n%s"], workdir, env, 30, out.append
        )
        sha = out[0].strip() if code == 0 and out else ""
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            # E.g. the first deploy is still fetching: no commit checked out yet.
            return {"exists": True, "commit_sha": None, "commit_message": None}
        return {
            "exists": True,
            "commit_sha": sha,
            "commit_message": out[1].strip()[:200] if len(out) > 1 else None,
        }

    def remove(self, name: str, compose_file: str, down: bool) -> dict:
        if not valid_project(name) or not valid_compose_file(compose_file):
            raise DockerError("invalid_project", 422)
        if name in self.protected_projects():
            raise DockerError("project_protected", 403)
        with self._lock:
            if name in self._busy:
                raise DockerError("deploy_in_progress", 409)
            self._busy.add(name)
        try:
            workdir = self._project_dir(name)
            output: list[str] = []
            if down:
                env = {
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": "/tmp",  # noqa: S108
                    "COMPOSE_PROGRESS": "plain",
                }
                args = ["docker", "compose", "-p", name, "down", "--remove-orphans"]
                cwd = workdir if workdir.exists() else self.root
                if workdir.exists() and (workdir / compose_file).exists():
                    args[4:4] = ["-f", compose_file]
                if self.runner.run(args, cwd, env, 300, output.append) != 0:
                    raise DockerError("down_failed", 502, "\n".join(output[-5:])[:300])
            if workdir.exists():
                shutil.rmtree(workdir)
            return {"removed": True}
        finally:
            with self._lock:
                self._busy.discard(name)


def _parse_ps(lines: list[str]) -> list[dict]:
    """`docker compose ps --format json`: one JSON object per line (or one JSON array)."""
    text = "\n".join(lines).strip()
    items: list[dict] = []
    if text.startswith("["):
        try:
            items = json.loads(text)
        except ValueError:
            items = []
    else:
        for line in lines:
            line = line.strip()
            if line.startswith("{"):
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue
    services = []
    for item in items:
        state = str(item.get("State", "")).lower()
        health = str(item.get("Health", "") or "").lower() or None
        code = item.get("ExitCode", 0)
        why = None
        if state == "restarting":
            why = "restarting"
        elif state in ("exited", "dead") and code not in (0, None):
            why = f"exited with code {code}"
        elif health == "unhealthy":
            why = "unhealthy"
        services.append(
            {
                "name": item.get("Service") or item.get("Name", "?"),
                "state": state,
                "health": health,
                "why": why,
            }
        )
    return services
