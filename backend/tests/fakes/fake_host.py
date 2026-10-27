"""A fake host for the web server manager: a directory tree plus stand-ins for nginx,
apachectl, systemctl, journalctl, certbot and a2enmod on PATH.

Commands log their arguments to <root>/calls.log. The configuration test fails while any
file under /etc contains "BROKEN"; a reload fails while <root>/fail-reload exists.
"""

import os
import stat
from pathlib import Path

from mbp.agent.hostexec import LocalRunner

TEST_SH = """#!/bin/sh
echo "$(basename "$0") $*" >> "$MBP_ROOT/calls.log"
case "$1" in
  -v) echo "nginx version: nginx/1.24.0" >&2; exit 0 ;;
esac
if grep -rqs BROKEN "$MBP_ROOT/etc"; then
  echo "syntax error: unexpected BROKEN" >&2
  exit 1
fi
echo "syntax is ok" >&2
"""
APACHECTL_SH = """#!/bin/sh
echo "$(basename "$0") $*" >> "$MBP_ROOT/calls.log"
if [ "$1" = "-v" ]; then echo "Server version: Apache/2.4.62 (Debian)"; exit 0; fi
if grep -rqs BROKEN "$MBP_ROOT/etc"; then echo "Syntax error on line 3" >&2; exit 1; fi
echo "Syntax OK" >&2
"""
SYSTEMCTL_SH = """#!/bin/sh
echo "systemctl $*" >> "$MBP_ROOT/calls.log"
case "$1" in
  show)
    echo "LoadState=loaded"
    echo "ActiveState=active"
    echo "SubState=running"
    echo "ActiveEnterTimestamp=Mon 2026-10-26 08:00:00 UTC"
    echo "MainPID=1234"
    ;;
  is-active) [ "$2" = certbot.timer ] && echo active || echo inactive ;;
  reload|restart)
    if [ -e "$MBP_ROOT/fail-reload" ]; then echo "Job for $2 failed" >&2; exit 1; fi ;;
esac
"""
JOURNALCTL_SH = """#!/bin/sh
echo "2026-10-27T10:00:00+0000 host systemd[1]: Reloading nginx.service"
echo "2026-10-27T10:00:01+0000 host systemd[1]: Reloaded nginx.service"
"""
LOGGER_SH = """#!/bin/sh
echo "$(basename "$0") $*" >> "$MBP_ROOT/calls.log"
echo "$(basename "$0") done"
"""


def _script(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class FakeHost:
    def __init__(self, root: Path, bin_dir: Path) -> None:
        self.root = root
        self.bin = bin_dir
        root.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)
        (root / "run/systemd/system").mkdir(parents=True, exist_ok=True)
        _script(bin_dir / "nginx", TEST_SH)
        for name in ("apache2ctl", "apachectl"):
            _script(bin_dir / name, APACHECTL_SH)
        _script(bin_dir / "systemctl", SYSTEMCTL_SH)
        _script(bin_dir / "journalctl", JOURNALCTL_SH)
        for name in ("certbot", "a2enmod", "apt-get"):
            _script(bin_dir / name, LOGGER_SH)
        self.runner = LocalRunner(str(root), path=f"{bin_dir}:{os.environ.get('PATH', '')}")

    def write(self, path: str, text: str) -> Path:
        target = self.root / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def link(self, path: str, target: str) -> None:
        where = self.root / path.lstrip("/")
        where.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, where)

    def read(self, path: str) -> str:
        return (self.root / path.lstrip("/")).read_text()

    def exists(self, path: str) -> bool:
        return os.path.lexists(self.root / path.lstrip("/"))

    def calls(self) -> list[str]:
        log = self.root / "calls.log"
        return log.read_text().splitlines() if log.exists() else []
