"""Host-wide CPU, memory and disk numbers, read from /proc and statvfs.

/proc/meminfo and /proc/stat are not namespaced, so inside the agent container they describe
the whole host. The disk is the filesystem holding the agent's root, i.e. Docker's data
directory.
"""

import os
import threading
import time
from pathlib import Path


class HostProbe:
    def __init__(self, proc: str | Path = "/proc", disk_path: str = "/") -> None:
        self.proc = Path(proc)
        self.disk_path = disk_path
        self._last_cpu: tuple[float, int, int] | None = None
        self._lock = threading.Lock()

    def _cpu_times(self) -> tuple[int, int]:
        """(busy, total) jiffies over all CPUs."""
        first = (self.proc / "stat").read_text().splitlines()[0].split()[1:]
        values = [int(v) for v in first]
        idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
        # guest time is already counted in user/nice
        total = sum(values[:8])
        return total - idle, total

    def cpu_percent(self) -> float | None:
        try:
            busy, total = self._cpu_times()
            with self._lock:
                last = self._last_cpu
                now = time.monotonic()
                if last is None or now - last[0] > 120:
                    # No recent sample: take a short one now.
                    time.sleep(0.25)
                    last = (now, busy, total)
                    busy, total = self._cpu_times()
                self._last_cpu = (time.monotonic(), busy, total)
            delta_total = total - last[2]
            if delta_total <= 0:
                return None
            return round((busy - last[1]) * 100 / delta_total, 1)
        except (OSError, ValueError, IndexError):
            return None

    def memory(self) -> tuple[int, int] | None:
        """(total, available) bytes."""
        try:
            fields = {}
            for line in (self.proc / "meminfo").read_text().splitlines():
                name, _, rest = line.partition(":")
                fields[name] = int(rest.split()[0]) * 1024
            return fields["MemTotal"], fields.get("MemAvailable", fields.get("MemFree", 0))
        except (OSError, ValueError, KeyError, IndexError):
            return None

    def load(self) -> list[float] | None:
        try:
            return [float(v) for v in (self.proc / "loadavg").read_text().split()[:3]]
        except (OSError, ValueError):
            return None

    def disk(self) -> tuple[int, int] | None:
        """(total, free) bytes."""
        try:
            st = os.statvfs(self.disk_path)
        except OSError:
            return None
        return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize

    def snapshot(self) -> dict:
        memory = self.memory()
        disk = self.disk()
        return {
            "cpu_percent": self.cpu_percent(),
            "load": self.load(),
            "memory_total": memory[0] if memory else None,
            "memory_available": memory[1] if memory else None,
            "disk_total": disk[0] if disk else None,
            "disk_free": disk[1] if disk else None,
        }
