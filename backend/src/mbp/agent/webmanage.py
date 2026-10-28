"""Managing the host's web servers: status, test, reload, files, sites, logs, certificates.

Every change is a transaction: the files are changed, the configuration is tested
(`nginx -t`, `apachectl configtest`) and the server reloaded; if the test or the reload fails,
every change is undone (and the server reloaded again), so a broken configuration never stays
on disk. A file is copied to /var/backups/mbp-webserver before it is overwritten. Only files
under the web server's own directory (/etc/nginx, /etc/apache2, /etc/httpd) are ever written.

Commands run on the host through a HostRunner (mbp.agent.hostexec); reads go through the
read-only mount of the host's /etc (mbp.agent.webserver.Reader).
"""

import base64
import hashlib
import logging
import os
import posixpath
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cryptography import x509

from mbp.agent.docker import DockerError
from mbp.agent.hostexec import HostResult, HostRunner
from mbp.agent.webserver import (
    APACHE_MAINS,
    DISABLED_SUFFIX,
    MAINTENANCE_PREFIX,
    NGINX_MAIN,
    ConfigError,
    Reader,
    maintenance_page,
    scan,
)

logger = logging.getLogger(__name__)

BACKUP_DIR = "/var/backups/mbp-webserver"
KEEP_BACKUPS = 20
# Content travels to the host in an environment variable (base64), which Linux limits to
# 128 KiB; configuration files are far smaller.
MAX_CONTENT_BYTES = 96 * 1024
MAX_LOG_LINES = 2000
COMMAND_TIMEOUT = 60
CERTBOT_TIMEOUT = 600
INSTALL_TIMEOUT = 900
JOB_TTL_SECONDS = 24 * 3600
# A backup's name: when it was taken (UTC, to the microsecond).
BACKUP_NAME = re.compile(r"\d{8}T\d{12}Z")

DOMAIN_RE = re.compile(r"(\*\.)?([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}")
SITE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
URL_RE = re.compile(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~/\-]*)?")
DIR_RE = re.compile(r"/[A-Za-z0-9._@/\-]*")
FPM_RE = re.compile(r"(unix:/[A-Za-z0-9._/\-]+|127\.0\.0\.1:\d{1,5}|localhost:\d{1,5})")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,63}")
TEMPLATES = ("proxy", "php", "static", "redirect")

STATUS_SH = r"""
svc=$1; bin=$2; shift 2
echo "==state=="
if command -v systemctl >/dev/null 2>&1 && [ -d "$MBP_ROOT/run/systemd/system" ]; then
  systemctl show "$svc" --no-pager -p LoadState -p ActiveState -p SubState \
    -p ActiveEnterTimestamp -p MainPID 2>/dev/null
  echo "==journal=="
  journalctl -u "$svc" -n 300 --no-pager -o short-iso 2>/dev/null \
    | grep -E "Reload(ed|ing) " | tail -n 1
fi
echo "==pid=="
pidof "$bin" 2>/dev/null || true
echo "==version=="
"$@" 2>&1 | head -n 3
"""
CONTROL_SH = r"""
svc=$1; act=$2; shift 2
if command -v systemctl >/dev/null 2>&1 && [ -d "$MBP_ROOT/run/systemd/system" ]; then
  exec systemctl "$act" "$svc"
fi
if [ "$#" -eq 0 ]; then echo "no systemd: cannot $act $svc" >&2; exit 3; fi
exec "$@"
"""
WRITE_SH = r"""
set -e
target=$1
tmp="$target.mbp-tmp"
mkdir -p "$(dirname "$target")"
printf '%s' "$MBP_CONTENT" | base64 -d > "$tmp"
if [ -e "$target" ]; then
  chmod --reference="$target" "$tmp" 2>/dev/null || true
  chown --reference="$target" "$tmp" 2>/dev/null || true
else
  chmod 644 "$tmp"
fi
mv -f "$tmp" "$target"
"""
BACKUP_SH = r"""
set -e
src=$1; dir=$2; name=$3; keep=$4
mkdir -p "$dir"
chmod 700 "$MBP_ROOT/var/backups/mbp-webserver" 2>/dev/null || true
cp -p "$src" "$dir/$name"
ls -1 "$dir" | sort -r | tail -n +"$((keep + 1))" | while read -r old; do rm -f "$dir/$old"; done
"""
CAT_SH = r"""
for f in "$@"; do
  printf '==MBP-FILE== %s\n' "$f"
  if [ -L "$f" ] && [ ! -e "$f" ]; then
    printf '==MBP-BROKEN== %s\n' "$(readlink -- "$f")"
  elif cat -- "$f" 2>/dev/null; then
    printf '\n'  # the next marker starts a line, even after a file without a final newline
  else
    printf '==MBP-UNREADABLE==\n'
  fi
done
"""
# How many rounds of reading files on the host a scan may take (includes inside them).
SCAN_ROUNDS = 3
SOCKETS_SH = r"""
r=$MBP_ROOT
for f in "$r"/run/php/*.sock "$r"/run/php-fpm/*.sock "$r"/var/run/php-fpm/*.sock; do
  [ -e "$f" ] && echo "${f#"$MBP_ROOT"}"
done
true
"""
CERTBOT_SH = r"""
if command -v certbot >/dev/null 2>&1; then
  echo "installed=1"
  certbot --version 2>&1 | head -n 1 | sed 's/^/version=/'
else
  echo "installed=0"
fi
if command -v systemctl >/dev/null 2>&1 && [ -d "$MBP_ROOT/run/systemd/system" ]; then
  for t in certbot.timer snap.certbot.renew.timer; do
    [ "$(systemctl is-active "$t" 2>/dev/null)" = active ] && echo "timer=$t"
  done
fi
[ -e "$MBP_ROOT/etc/cron.d/certbot" ] && echo "cron=/etc/cron.d/certbot"
command -v apt-get >/dev/null 2>&1 && echo "pm=apt"
command -v dnf >/dev/null 2>&1 && echo "pm=dnf"
command -v yum >/dev/null 2>&1 && echo "pm=yum"
true
"""
INSTALL_SH = r"""
set -e
plugin=$1
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y certbot "python3-certbot-$plugin"
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y certbot "python3-certbot-$plugin"
elif command -v yum >/dev/null 2>&1; then
  yum install -y certbot "python3-certbot-$plugin"
else
  echo "No apt-get, dnf or yum on this server: install certbot by hand." >&2
  exit 2
fi
"""
MAINTENANCE_HTML = (
    "<!doctype html><html><head><meta charset=utf-8><title>Maintenance</title></head>"
    "<body style=font-family:sans-serif;text-align:center;padding:60px>"
    "<h1>Under maintenance</h1><p>We will be back shortly.</p>"
    "<p dir=rtl>&#1583;&#1585; &#1581;&#1575;&#1604; &#1576;&#1607;&#8204;&#1585;&#1608;&#1586;"
    "&#1585;&#1587;&#1575;&#1606;&#1740;</p></body></html>"
)


class WebError(DockerError):
    """A refused request: the agent answers it with this status and code."""


@dataclass(frozen=True)
class Flavor:
    kind: str  # nginx | apache
    service: str
    binary: str
    conf_dir: str
    test: list[str]
    version: list[str]
    fallback: dict[str, list[str]]
    debian: bool  # sites-available / sites-enabled
    plugin: str  # certbot's plugin

    @property
    def available_dir(self) -> str:
        return f"{self.conf_dir}/sites-available"

    @property
    def enabled_dir(self) -> str:
        return f"{self.conf_dir}/sites-enabled"

    @property
    def confd(self) -> str:
        return f"{self.conf_dir}/conf.d"


NGINX = Flavor(
    "nginx",
    "nginx",
    "nginx",
    "/etc/nginx",
    ["nginx", "-t"],
    ["nginx", "-v"],
    {"reload": ["nginx", "-s", "reload"]},
    True,
    "nginx",
)
APACHE2 = Flavor(
    "apache",
    "apache2",
    "apache2",
    "/etc/apache2",
    ["apache2ctl", "configtest"],
    ["apache2ctl", "-v"],
    {"reload": ["apache2ctl", "graceful"], "restart": ["apache2ctl", "restart"]},
    True,
    "apache",
)
HTTPD = Flavor(
    "apache",
    "httpd",
    "httpd",
    "/etc/httpd",
    ["apachectl", "configtest"],
    ["httpd", "-v"],
    {"reload": ["apachectl", "graceful"], "restart": ["apachectl", "restart"]},
    False,
    "apache",
)


def flat(path: str) -> str:
    return path.strip("/").replace("/", "__")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


# --- jobs (certbot can take minutes) ---


@dataclass
class Job:
    id: str
    action: str
    target: str
    status: str = "running"  # running | success | failed
    output: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def view(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "target": self.target,
            "status": self.status,
            "output": self.output,
            "started_at": datetime.fromtimestamp(self.started_at, UTC).isoformat(),
            "finished_at": (
                datetime.fromtimestamp(self.finished_at, UTC).isoformat()
                if self.finished_at
                else None
            ),
        }


class Jobs:
    def __init__(self, background: bool = True) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.background = background

    def start(self, action: str, target: str, work: Callable[[], HostResult]) -> Job:
        job = Job(uuid.uuid4().hex, action, target)
        with self._lock:
            cutoff = time.time() - JOB_TTL_SECONDS
            self._jobs = {k: j for k, j in self._jobs.items() if j.started_at > cutoff}
            self._jobs[job.id] = job

        def run() -> None:
            try:
                result = work()
                job.output = result.output
                job.status = "success" if result.ok else "failed"
            except Exception as exc:  # reported in the job, never lost
                logger.exception("Web server job %s failed", action)
                job.output = str(getattr(exc, "code", "") or exc)
                job.status = "failed"
            job.finished_at = time.time()

        if self.background:
            threading.Thread(target=run, name=f"mbp-web-{action}", daemon=True).start()
        else:
            run()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


# --- transactions ---


@dataclass
class Change:
    """One step of a transaction and how to undo it (argument lists for the host)."""

    do: list[list[str] | tuple[list[str], dict]]
    undo: list[list[str] | tuple[list[str], dict]]


class WebManager:
    def __init__(self, root: str, runner: HostRunner, jobs: Jobs | None = None) -> None:
        self.root = root  # the host's / as mounted (read-only)
        self.runner = runner
        self.jobs = jobs or Jobs()
        self._lock = threading.Lock()

    # --- helpers ---

    def reader(self) -> Reader:
        return Reader(self.root)

    def scan(self) -> dict:
        """The web servers and their sites, reading on the host what the mount cannot give.

        Files outside the mounted /etc (a sites-available that is a link elsewhere) or not
        readable by the agent are read by the helper; a link to nothing is reported as one.
        """
        preloaded: dict = {}
        result: dict = {}
        for _ in range(SCAN_ROUNDS + 1):
            missing: set[str] = set()
            result = scan(self.root, preloaded, missing)
            todo = sorted(missing - preloaded.keys())
            if not todo:
                break
            try:
                out = self.sh(CAT_SH, *[self.host(p) for p in todo])
            except DockerError:
                break  # no helper: report what the mount gave
            found = split_files(out.stdout, self.runner.prefix)
            for path in todo:
                preloaded[path] = found.get(path)
        return result

    def flavor(self, kind: str) -> Flavor:
        reader = self.reader()
        if kind == "nginx" and reader.exists(NGINX_MAIN):
            return NGINX
        if kind == "apache":
            if reader.exists(APACHE_MAINS[0]):
                return APACHE2
            if reader.exists(APACHE_MAINS[1]):
                return HTTPD
        raise WebError("webserver_not_found", 404)

    def host(self, path: str) -> str:
        """A host path as the runner's commands see it."""
        return self.runner.prefix + path

    def run(self, argv: list[str], env: dict | None = None, timeout: float = COMMAND_TIMEOUT):
        return self.runner.run(
            argv, env={"MBP_ROOT": self.runner.prefix, **(env or {})}, timeout=timeout
        )

    def sh(self, script: str, *args: str, env: dict | None = None, timeout: float = 60):
        return self.run(["sh", "-c", script, "sh", *args], env=env, timeout=timeout)

    def owned(self, flavor: Flavor, path: str) -> str:
        """The real path of a file in the web server's directory, or a 403."""
        if not path.startswith("/") or "\x00" in path or "/../" in f"{path}/":
            raise WebError("path_not_allowed", 403)
        try:
            real = self.reader().resolve(path)
        except ConfigError as exc:
            raise WebError("path_not_allowed", 403) from exc
        if not real.startswith(flavor.conf_dir + "/"):
            raise WebError("path_not_allowed", 403)
        return real

    def read_text(self, path: str) -> str | None:
        """A host file's text through the mount; None if it does not exist."""
        reader = self.reader()
        if not reader.exists(path):
            return None
        try:
            return reader.read(path)[1]
        except ConfigError as exc:
            raise WebError("file_unreadable", 409, str(exc)) from exc

    def write_step(self, path: str, content: str) -> tuple[list[str], dict]:
        data = content.encode()
        if len(data) > MAX_CONTENT_BYTES:
            raise WebError("file_too_large", 413)
        env = {"MBP_CONTENT": base64.b64encode(data).decode()}
        return ["sh", "-c", WRITE_SH, "sh", self.host(path)], env

    def put_step(self, path: str, old: str | None, new: str) -> Change:
        """Write `new`; undone by writing `old` back (or removing the new file)."""
        undo = [self.write_step(path, old)] if old is not None else [self.rm(path)]
        return Change([self.write_step(path, new)], undo)

    def rm(self, path: str) -> list[str]:
        return ["rm", "-f", "--", self.host(path)]

    def ln(self, target: str, link: str) -> list[str]:
        return ["ln", "-s", "--", target, self.host(link)]

    def mv(self, src: str, dst: str) -> list[str]:
        return ["mv", "--", self.host(src), self.host(dst)]

    def _step(self, step) -> HostResult:
        argv, env = step if isinstance(step, tuple) else (step, None)
        return self.run(argv, env)

    def control_argv(self, flavor: Flavor, action: str) -> list[str]:
        return [
            "sh",
            "-c",
            CONTROL_SH,
            "sh",
            flavor.service,
            action,
            *flavor.fallback.get(action, []),
        ]

    def apply(self, flavor: Flavor, changes: list[Change], *, reload: bool = True) -> dict:
        """Make the changes, test, reload; undo everything if any step fails."""
        with self._lock:
            done: list[Change] = []
            for change in changes:
                for step in change.do:
                    result = self._step(step)
                    if not result.ok:
                        done.append(change)
                        self._undo(done)
                        return {"ok": False, "code": "command_failed", "output": result.output}
                done.append(change)
            test = self.run(flavor.test)
            if not test.ok:
                self._undo(done)
                return {"ok": False, "code": "config_test_failed", "output": test.output}
            if not reload:
                return {"ok": True, "code": None, "output": test.output}
            loaded = self.run(self.control_argv(flavor, "reload"))
            if not loaded.ok:
                self._undo(done)
                self.run(self.control_argv(flavor, "reload"))
                return {
                    "ok": False,
                    "code": "reload_failed",
                    "output": "\n".join(filter(None, [test.output, loaded.output])),
                }
            return {
                "ok": True,
                "code": None,
                "output": "\n".join(filter(None, [test.output, loaded.output])),
            }

    def _undo(self, done: list[Change]) -> None:
        for change in reversed(done):
            for step in change.undo:
                result = self._step(step)
                if not result.ok:
                    logger.error("Could not undo a web server change: %s", result.output)

    # --- status and control ---

    def status(self) -> dict:
        found = []
        reader = self.reader()
        flavors = [NGINX] if reader.exists(NGINX_MAIN) else []
        if reader.exists(APACHE_MAINS[0]):
            flavors.append(APACHE2)
        elif reader.exists(APACHE_MAINS[1]):
            flavors.append(HTTPD)
        for flavor in flavors:
            result = self.sh(STATUS_SH, flavor.service, flavor.binary, *flavor.version)
            found.append({"kind": flavor.kind, "service": flavor.service, **parse_status(result)})
        return {"servers": found}

    def test(self, kind: str) -> dict:
        result = self.run(self.flavor(kind).test)
        return {"ok": result.ok, "output": result.output}

    def control(self, kind: str, action: str) -> dict:
        if action not in ("reload", "restart"):
            raise WebError("invalid_action", 400)
        flavor = self.flavor(kind)
        with self._lock:
            test = self.run(flavor.test)
            if not test.ok:
                return {"ok": False, "code": "config_test_failed", "output": test.output}
            result = self.run(self.control_argv(flavor, action))
        return {
            "ok": result.ok,
            "code": None if result.ok else f"{action}_failed",
            "output": "\n".join(filter(None, [test.output, result.output])),
        }

    # --- files ---

    def read_file(self, kind: str, path: str) -> dict:
        flavor = self.flavor(kind)
        real = self.owned(flavor, path)
        text = self.read_text(real)
        if text is None:
            raise WebError("file_not_found", 404)
        return {"path": real, "content": text, "sha256": sha256(text), "size": len(text)}

    def backup_step(self, path: str, name: str) -> list[str]:
        return [
            "sh",
            "-c",
            BACKUP_SH,
            "sh",
            self.host(path),
            self.host(f"{BACKUP_DIR}/{flat(path)}"),
            name,
            str(KEEP_BACKUPS),
        ]

    def write_file(self, kind: str, path: str, content: str, expected: str | None) -> dict:
        flavor = self.flavor(kind)
        real = self.owned(flavor, path)
        old = self.read_text(real)
        if old is None:
            raise WebError("file_not_found", 404)
        if expected is not None and sha256(old) != expected:
            raise WebError("file_changed", 409)
        if old == content:
            return {"ok": True, "code": None, "output": "", "path": real}
        name = _now()
        backup = self._step(self.backup_step(real, name))
        if not backup.ok:
            return {"ok": False, "code": "backup_failed", "output": backup.output}
        result = self.apply(flavor, [self.put_step(real, old, content)])
        if not result["ok"]:
            # Nothing changed: the copy would only repeat the current version.
            self._step(self.rm(f"{BACKUP_DIR}/{flat(real)}/{name}"))
        return {**result, "path": real}

    def backups(self, kind: str, path: str) -> dict:
        real = self.owned(self.flavor(kind), path)
        listing = self.run(["ls", "-1", "--", self.host(f"{BACKUP_DIR}/{flat(real)}")])
        names = [n for n in listing.stdout.split() if BACKUP_NAME.fullmatch(n)]
        return {"path": real, "backups": sorted(names, reverse=True)}

    def read_backup(self, kind: str, path: str, backup: str) -> str:
        real = self.owned(self.flavor(kind), path)
        if not BACKUP_NAME.fullmatch(backup):
            raise WebError("backup_not_found", 404)
        result = self.run(["cat", "--", self.host(f"{BACKUP_DIR}/{flat(real)}/{backup}")])
        if not result.ok:
            raise WebError("backup_not_found", 404)
        return result.stdout

    def restore(self, kind: str, path: str, backup: str) -> dict:
        content = self.read_backup(kind, path, backup)
        return self.write_file(kind, path, content, None)

    # --- sites ---

    def _site(self, flavor: Flavor, path: str) -> dict:
        """The scan's view of a file (the first site defined in it)."""
        real = self.owned(flavor, path)
        for server in self.scan()["servers"]:
            if server["kind"] != flavor.kind:
                continue
            for site in server["sites"]:
                if site["file"] == real:
                    return site
        raise WebError("site_not_found", 404)

    def _links_to(self, flavor: Flavor, real: str) -> list[tuple[str, str]]:
        """(link, its target) of every sites-enabled entry that is `real`."""
        reader = self.reader()
        out = []
        for name in reader.listdir(flavor.enabled_dir):
            link = f"{flavor.enabled_dir}/{name}"
            local = reader.local(link)
            if not os.path.islink(local):
                continue
            try:
                if reader.resolve(link) == real:
                    out.append((link, os.readlink(local)))
            except ConfigError:
                continue
        return out

    def _off_steps(self, flavor: Flavor, real: str) -> list[Change]:
        """Changes that stop the server loading a file."""
        if real.startswith(flavor.available_dir + "/"):
            links = self._links_to(flavor, real)
            return [Change([self.rm(link)], [self.ln(target, link)]) for link, target in links]
        if real.startswith(flavor.enabled_dir + "/"):
            moved = f"{flavor.available_dir}/{posixpath.basename(real)}"
            if self.reader().exists(moved):
                raise WebError("site_name_taken", 409)
            return [Change([self.mv(real, moved)], [self.mv(moved, real)])]
        if not real.endswith(DISABLED_SUFFIX):
            off = real + DISABLED_SUFFIX
            return [Change([self.mv(real, off)], [self.mv(off, real)])]
        return []

    def _on_steps(self, flavor: Flavor, real: str) -> list[Change]:
        """Changes that make the server load a file again."""
        if real.startswith(flavor.available_dir + "/"):
            if self._links_to(flavor, real):
                return []
            name = posixpath.basename(real)
            link = f"{flavor.enabled_dir}/{name}"
            if self.reader().exists(link):
                raise WebError("site_name_taken", 409)
            return [Change([self.ln(f"../sites-available/{name}", link)], [self.rm(link)])]
        if real.endswith(DISABLED_SUFFIX):
            on = real[: -len(DISABLED_SUFFIX)]
            if self.reader().exists(on):
                raise WebError("site_name_taken", 409)
            return [Change([self.mv(real, on)], [self.mv(on, real)])]
        return []

    def set_enabled(self, kind: str, path: str, enabled: bool) -> dict:
        flavor = self.flavor(kind)
        real = self.owned(flavor, path)
        if not self.reader().exists(real):
            raise WebError("file_not_found", 404)
        steps = self._on_steps(flavor, real) if enabled else self._off_steps(flavor, real)
        if not steps:
            return {"ok": True, "code": None, "output": ""}
        return self.apply(flavor, steps)

    def set_maintenance(self, kind: str, path: str, on: bool) -> dict:
        flavor = self.flavor(kind)
        real = self.owned(flavor, path)
        if posixpath.basename(real).startswith(MAINTENANCE_PREFIX):
            raise WebError("path_not_allowed", 403)
        page = maintenance_page(flavor.conf_dir, flavor.kind, real)
        exists = self.reader().exists(page)
        if on:
            if exists:
                return {"ok": True, "code": None, "output": ""}
            sites = [
                s
                for server in self.scan()["servers"]
                if server["kind"] == flavor.kind
                for s in server["sites"]
                if s["file"] == real
            ]
            if not sites:
                raise WebError("site_not_found", 404)
            content = maintenance_config(flavor, sites)
            steps = self._off_steps(flavor, real)
            steps.append(self.put_step(page, None, content))
            steps += self._on_steps_for_new(flavor, page)
            return self.apply(flavor, steps)
        if not exists:
            return {"ok": True, "code": None, "output": ""}
        old = self.read_text(page) or ""
        steps = self._off_steps(flavor, page) if page.startswith(flavor.available_dir) else []
        steps.append(Change([self.rm(page)], [self.write_step(page, old)]))
        original = real
        if not self.reader().exists(original) and self.reader().exists(original + DISABLED_SUFFIX):
            original += DISABLED_SUFFIX
        steps += self._on_steps(flavor, original)
        return self.apply(flavor, steps)

    def _on_steps_for_new(self, flavor: Flavor, path: str) -> list[Change]:
        """Links a new file in sites-available (it does not exist yet, so no scan)."""
        if not path.startswith(flavor.available_dir + "/"):
            return []
        name = posixpath.basename(path)
        link = f"{flavor.enabled_dir}/{name}"
        if self.reader().exists(link):
            raise WebError("site_name_taken", 409)
        return [Change([self.ln(f"../sites-available/{name}", link)], [self.rm(link)])]

    def new_site_path(self, flavor: Flavor, name: str) -> str:
        # Debian's Apache always has sites-available; nginx.org's packages only conf.d.
        if flavor.service == "apache2" or (
            flavor.debian and self.reader().is_dir(flavor.available_dir)
        ):
            ext = ".conf" if flavor.kind == "apache" else ""
            return f"{flavor.available_dir}/{name}{ext}"
        return f"{flavor.confd}/{name}.conf"

    def create_site(self, kind: str, spec: dict) -> dict:
        flavor = self.flavor(kind)
        # Listen on IPv6 only where the server's own sites do (some hosts have no IPv6).
        ipv6 = any(
            "[::" in listen
            for server in self.scan()["servers"]
            if server["kind"] == "nginx"
            for site in server["sites"]
            if site["enabled"]
            for listen in site.get("listen") or []
        )
        name, content, modules = render_site(flavor, spec, ipv6)
        path = self.new_site_path(flavor, name)
        reader = self.reader()
        if reader.exists(path) or reader.exists(path + DISABLED_SUFFIX):
            raise WebError("site_name_taken", 409)
        steps = [self.put_step(path, None, content)]
        steps += self._on_steps_for_new(flavor, path)
        if modules and flavor.service == "apache2":
            # a2enmod is idempotent; a module left on after a failed test does no harm.
            steps.insert(0, Change([["a2enmod", "-q", *modules]], []))
        result = self.apply(flavor, steps)
        return {**result, "path": path}

    def remove_broken_links(self, kind: str, paths: list[str]) -> dict:
        """Removes links to missing files from the enabled directories, then tests and reloads.

        Such a link makes the configuration test (and so every reload) fail.
        """
        flavor = self.flavor(kind)
        allowed = tuple(f"{flavor.conf_dir}/{d}/" for d in ("sites-enabled", "conf-enabled"))
        changes: list[Change] = []
        reader = self.reader()
        candidates = []
        for path in dict.fromkeys(paths):
            if not path.startswith(allowed) or "/../" in f"{path}/" or path.count("/") != 4:
                raise WebError("path_not_allowed", 403)
            local = reader.local(path)
            if os.path.islink(local):
                candidates.append((path, os.readlink(local)))
        if not candidates:
            return {"ok": True, "code": None, "output": "", "removed": []}
        found = split_files(
            self.sh(CAT_SH, *[self.host(p) for p, _ in candidates]).stdout, self.runner.prefix
        )
        removed = []
        for path, target in candidates:
            if isinstance(found.get(path), dict):  # still a link to nothing on the host
                changes.append(Change([self.rm(path)], [self.ln(target, path)]))
                removed.append(path)
        if not changes:
            return {"ok": True, "code": None, "output": "", "removed": []}
        return {**self.apply(flavor, changes), "removed": removed}

    # --- logs ---

    def log_paths(self, kind: str) -> set[str]:
        paths: set[str] = set()
        for server in self.scan()["servers"]:
            if server["kind"] != kind:
                continue
            for site in server["sites"]:
                paths.update(p for p in (site.get("logs") or {}).values() if p)
        return paths

    def logs(self, kind: str, path: str, lines: int) -> dict:
        self.flavor(kind)
        if path not in self.log_paths(kind):
            raise WebError("log_not_found", 404)
        lines = max(1, min(lines, MAX_LOG_LINES))
        result = self.run(["tail", "-n", str(lines), "--", self.host(path)])
        if not result.ok:
            raise WebError("log_unreadable", 409, result.output[:300])
        text = result.stdout.splitlines()
        return {"path": path, "lines": text[-lines:]}

    # --- certificates ---

    def certificates(self) -> dict:
        paths = sorted(
            {
                site["certificate"]
                for server in self.scan()["servers"]
                for site in server["sites"]
                if site.get("certificate") and "$" not in site["certificate"]
            }
        )
        found: dict[str, dict] = {}
        missing: list[str] = []
        reader = self.reader()
        for path in paths:
            try:
                found[path] = cert_info(reader.read(path)[1])
            except ConfigError:
                missing.append(path)
        if missing:
            result = self.sh(CAT_SH, *[self.host(p) for p in missing])
            for path, text in split_files(result.stdout, self.runner.prefix).items():
                found[path] = (
                    cert_info(text)
                    if isinstance(text, str)
                    else {"error": "certificate_unreadable"}
                )
        for path in paths:
            found.setdefault(path, {"error": "certificate_unreadable"})
        return {"certificates": found}

    def php_sockets(self) -> dict:
        result = self.sh(SOCKETS_SH)
        return {"sockets": [f"unix:{line}" for line in result.stdout.split() if line]}

    # --- certbot ---

    def certbot(self) -> dict:
        result = self.sh(CERTBOT_SH)
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            key, _, value = line.partition("=")
            values.setdefault(key.strip(), value.strip())
        auto = values.get("timer") or values.get("cron")
        return {
            "installed": values.get("installed") == "1",
            "version": (values.get("version") or "").removeprefix("certbot ").strip() or None,
            "auto_renew": auto,
            "package_manager": values.get("pm"),
        }

    def certbot_issue(self, kind: str, domains: list[str], email: str | None, redirect: bool):
        flavor = self.flavor(kind)
        names = [d.strip().lower() for d in domains if d.strip()]
        if not names or len(names) > 50 or not all(DOMAIN_RE.fullmatch(n) for n in names):
            raise WebError("invalid_domain", 400)
        if any(n.startswith("*.") for n in names):
            # Wildcards need a DNS challenge, which the web server plugins cannot do.
            raise WebError("wildcard_not_supported", 400)
        if email and not EMAIL_RE.fullmatch(email):
            raise WebError("invalid_email", 400)
        argv = [
            "certbot",
            f"--{flavor.plugin}",
            "--non-interactive",
            "--agree-tos",
            "--keep-until-expiring",
            "--cert-name",
            names[0],
            *(["-m", email] if email else ["--register-unsafely-without-email"]),
            "--redirect" if redirect else "--no-redirect",
        ]
        for name in names:
            argv += ["-d", name]
        return self.jobs.start(
            "certbot_issue", " ".join(names), lambda: self.run(argv, timeout=CERTBOT_TIMEOUT)
        )

    def certbot_renew(self):
        argv = ["certbot", "renew", "--non-interactive"]
        return self.jobs.start("certbot_renew", "", lambda: self.run(argv, timeout=CERTBOT_TIMEOUT))

    def certbot_install(self, kind: str):
        flavor = self.flavor(kind)
        return self.jobs.start(
            "certbot_install",
            flavor.plugin,
            lambda: self.sh(INSTALL_SH, flavor.plugin, timeout=INSTALL_TIMEOUT),
        )


# --- parsing command output ---


def parse_status(result: HostResult) -> dict:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"==(\w+)==", line.strip())
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
        elif line.strip():
            sections.setdefault(current, []).append(line.strip())
    props = dict(line.split("=", 1) for line in sections.get("state", []) if "=" in line)
    pids = " ".join(sections.get("pid", [])).split()
    systemd = bool(props)
    if systemd and props.get("LoadState") == "not-found":
        state = "not_installed"
    elif systemd:
        state = props.get("ActiveState") or "unknown"
    else:
        state = "active" if pids else "inactive"
    version_text = " ".join(sections.get("version", []))
    version = re.search(r"(nginx|Apache)/(\S+)", version_text)
    reload_line = (sections.get("journal") or [""])[-1]
    return {
        "state": state,
        "sub_state": props.get("SubState") or None,
        "since": props.get("ActiveEnterTimestamp") or None,
        "pid": int(props["MainPID"]) if props.get("MainPID", "0") not in ("", "0") else None,
        "version": version.group(2) if version else None,
        "last_reload": reload_line.split(" ", 1)[0] if reload_line else None,
        "systemd": systemd,
    }


def split_files(stdout: str, prefix: str) -> dict[str, str | dict | None]:
    """CAT_SH's output: host path -> text, None (unreadable) or {"broken": link target}."""
    out: dict[str, str | dict | None] = {}
    current = None
    lines: list[str] = []

    def text() -> str:
        return "".join(lines).removesuffix("\n")  # the newline CAT_SH adds after each file

    for line in stdout.splitlines(keepends=True):
        if line.startswith("==MBP-FILE== "):
            if current is not None:
                out[current] = text()
            current = line[len("==MBP-FILE== ") :].rstrip("\n").removeprefix(prefix)
            lines = []
        elif line.rstrip("\n") == "==MBP-UNREADABLE==" and current is not None:
            out[current] = None
            current = None
        elif line.startswith("==MBP-BROKEN== ") and current is not None:
            out[current] = {"broken": line[len("==MBP-BROKEN== ") :].rstrip("\n")}
            current = None
        else:
            lines.append(line)
    if current is not None:
        out[current] = text()
    return out


def cert_info(pem: str) -> dict:
    """Validity, names and issuer of the first certificate in a PEM file."""
    match = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", pem, re.S)
    if not match:
        return {"error": "certificate_invalid"}
    try:
        cert = x509.load_pem_x509_certificate(match.group(0).encode())
    except ValueError:
        return {"error": "certificate_invalid"}
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = san.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        names = []

    def attr(name: x509.Name, oid) -> str | None:
        found = name.get_attributes_for_oid(oid)
        return str(found[0].value) if found else None

    issuer = attr(cert.issuer, x509.NameOID.ORGANIZATION_NAME) or attr(
        cert.issuer, x509.NameOID.COMMON_NAME
    )
    return {
        "subject": attr(cert.subject, x509.NameOID.COMMON_NAME),
        "names": names,
        "issuer": issuer,
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "error": None,
    }


# --- generated configuration ---


def _names(spec: dict) -> list[str]:
    names = [str(n).strip().lower() for n in spec.get("domains") or [] if str(n).strip()]
    if not names or len(names) > 50 or not all(DOMAIN_RE.fullmatch(n) for n in names):
        raise WebError("invalid_domain", 400)
    return list(dict.fromkeys(names))


def _field(spec: dict, key: str, pattern: re.Pattern, code: str) -> str:
    value = str(spec.get(key) or "").strip()
    if not pattern.fullmatch(value) or ".." in value:
        raise WebError(code, 400)
    return value


def render_site(flavor: Flavor, spec: dict, ipv6: bool = True) -> tuple[str, str, list[str]]:
    """(file name, content, Apache modules it needs) for a new site from a template.

    `ipv6`: nginx also listens on [::]; a host without IPv6 refuses such a site.
    """
    template = spec.get("template")
    if template not in TEMPLATES:
        raise WebError("invalid_template", 400)
    names = _names(spec)
    name = str(spec.get("name") or names[0].removeprefix("*.")).strip().lower()
    name = re.sub(r"[^a-z0-9_-]", "-", name)
    if not SITE_NAME_RE.fullmatch(name) or name.startswith(MAINTENANCE_PREFIX.rstrip("-")):
        raise WebError("invalid_site_name", 400)
    values: dict[str, str] = {}
    if template == "proxy":
        values["target"] = _field(spec, "target", URL_RE, "invalid_target")
    elif template == "php":
        values["root"] = _field(spec, "root", DIR_RE, "invalid_root")
        values["fpm"] = _field(spec, "php_fpm", FPM_RE, "invalid_php_fpm")
    elif template == "static":
        values["root"] = _field(spec, "root", DIR_RE, "invalid_root")
    else:
        values["target"] = _field(spec, "target", URL_RE, "invalid_target").rstrip("/")
        values["code"] = "301" if spec.get("permanent", True) else "302"
        values["keep_path"] = "1" if spec.get("keep_path", True) else ""
    header = (
        f"# Created by DevOps Manager on {datetime.now(UTC):%Y-%m-%d} ({template}).\n"
        "# You can edit it like any other site; the panel reads it from disk.\n"
    )
    if flavor.kind == "nginx":
        return name, header + _nginx_site(name, names, template, values, ipv6), []
    body, modules = _apache_site(flavor, name, names, template, values)
    return name, header + body, modules


def _nginx_site(name: str, names: list[str], template: str, v: dict, ipv6: bool) -> str:
    lines = [
        "server {",
        "    listen 80;",
        *(["    listen [::]:80;"] if ipv6 else []),
        f"    server_name {' '.join(names)};",
        "",
        f"    access_log /var/log/nginx/{name}.access.log;",
        f"    error_log /var/log/nginx/{name}.error.log;",
        "",
    ]
    if template == "proxy":
        lines += [
            "    client_max_body_size 50m;",
            "",
            "    location / {",
            f"        proxy_pass {v['target']};",
            "        proxy_http_version 1.1;",
            "        proxy_set_header Host $host;",
            "        proxy_set_header X-Real-IP $remote_addr;",
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "        proxy_set_header X-Forwarded-Proto $scheme;",
            "        proxy_set_header Upgrade $http_upgrade;",
            "        proxy_set_header Connection $http_connection;",
            "        proxy_read_timeout 300s;",
            "    }",
        ]
    elif template == "php":
        lines += [
            f"    root {v['root']};",
            "    index index.php index.html;",
            "",
            "    location / {",
            "        try_files $uri $uri/ /index.php?$query_string;",
            "    }",
            "",
            "    location ~ \\.php$ {",
            "        include fastcgi_params;",
            "        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;",
            f"        fastcgi_pass {v['fpm']};",
            "    }",
            "",
            "    location ~ /\\.(?!well-known) {",
            "        deny all;",
            "    }",
        ]
    elif template == "static":
        lines += [
            f"    root {v['root']};",
            "    index index.html index.htm;",
            "",
            "    location / {",
            "        try_files $uri $uri/ =404;",
            "    }",
        ]
    else:
        suffix = "$request_uri" if v["keep_path"] else ""
        lines += [f"    return {v['code']} {v['target']}{suffix};"]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _apache_site(
    flavor: Flavor, name: str, names: list[str], template: str, v: dict
) -> tuple[str, list[str]]:
    if flavor.service == "apache2":
        logs = [
            f"    ErrorLog ${{APACHE_LOG_DIR}}/{name}.error.log",
            f"    CustomLog ${{APACHE_LOG_DIR}}/{name}.access.log combined",
        ]
    else:
        logs = [
            f"    ErrorLog logs/{name}-error_log",
            f"    CustomLog logs/{name}-access_log combined",
        ]
    lines = ["<VirtualHost *:80>", f"    ServerName {names[0]}"]
    if names[1:]:
        lines.append(f"    ServerAlias {' '.join(names[1:])}")
    lines += [*logs, ""]
    modules: list[str] = []
    if template == "proxy":
        target = v["target"].rstrip("/") + "/"
        lines += [
            "    ProxyPreserveHost On",
            "    ProxyRequests Off",
            f"    ProxyPass / {target}",
            f"    ProxyPassReverse / {target}",
        ]
        modules = ["proxy", "proxy_http"]
    elif template in ("php", "static"):
        lines += [
            f'    DocumentRoot "{v["root"]}"',
            f'    <Directory "{v["root"]}">',
            "        Options -Indexes +FollowSymLinks",
            "        AllowOverride All",
            "        Require all granted",
            "    </Directory>",
        ]
        if template == "php":
            fpm = v["fpm"]
            handler = (
                f"proxy:{fpm}|fcgi://localhost"
                if fpm.startswith("unix:")
                else f"proxy:fcgi://{fpm}"
            )
            lines += [
                "    DirectoryIndex index.php index.html",
                "    <FilesMatch \\.php$>",
                f'        SetHandler "{handler}"',
                "    </FilesMatch>",
            ]
            modules = ["proxy", "proxy_fcgi"]
    else:
        if v["keep_path"]:
            lines.append(f"    Redirect {v['code']} / {v['target']}/")
        else:
            lines.append(f"    RedirectMatch {v['code']} ^ {v['target']}/")
        modules = ["alias"]
    lines.append("</VirtualHost>")
    return "\n".join(lines) + "\n", modules


def maintenance_config(flavor: Flavor, sites: list[dict]) -> str:
    """A 503 page for the same names, ports and certificates as `sites`."""
    header = (
        "# Maintenance page written by DevOps Manager; turn maintenance off in the panel\n"
        f"# to bring back {sites[0]['file']}.\n"
    )
    blocks = []
    for site in sites:
        if flavor.kind == "nginx":
            blocks.append(_nginx_maintenance(site))
        else:
            blocks.append(_apache_maintenance(site))
    return header + "\n".join(blocks)


def _nginx_maintenance(site: dict) -> str:
    lines = ["server {"]
    for listen in site.get("listen") or ["80"]:
        lines.append(f"    listen {listen};")
    if site["names"]:
        lines.append(f"    server_name {' '.join(site['names'])};")
    if site.get("certificate") and site.get("certificate_key"):
        lines.append(f"    ssl_certificate {site['certificate']};")
        lines.append(f"    ssl_certificate_key {site['certificate_key']};")
    if site.get("redirect") and not site.get("backends") and not site.get("root"):
        lines.append(f"    return 301 {site['redirect']};")
    else:
        lines += [
            "    location / {",
            "        default_type text/html;",
            "        add_header Retry-After 600 always;",
            f"        return 503 '{MAINTENANCE_HTML}';",
            "    }",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _apache_maintenance(site: dict) -> str:
    addresses = " ".join(site.get("addresses") or ["*:80"])
    lines = [f"<VirtualHost {addresses}>"]
    if site["names"]:
        lines.append(f"    ServerName {site['names'][0]}")
        if site["names"][1:]:
            lines.append(f"    ServerAlias {' '.join(site['names'][1:])}")
    if site.get("ssl") and site.get("certificate") and site.get("certificate_key"):
        lines += [
            "    SSLEngine on",
            f'    SSLCertificateFile "{site["certificate"]}"',
            f'    SSLCertificateKeyFile "{site["certificate_key"]}"',
        ]
        if site.get("certificate_chain"):
            lines.append(f'    SSLCertificateChainFile "{site["certificate_chain"]}"')
    if site.get("redirect") and not site.get("backends") and not site.get("root"):
        lines.append(f"    Redirect permanent / {site['redirect']}")
    else:
        lines += [
            f'    ErrorDocument 503 "{MAINTENANCE_HTML}"',
            "    RedirectMatch 503 ^/",
        ]
    lines.append("</VirtualHost>")
    return "\n".join(lines) + "\n"
