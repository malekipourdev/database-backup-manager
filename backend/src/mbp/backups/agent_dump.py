"""A dump run by another server's agent, streamed into the panel's backup file."""

import threading
from collections.abc import Callable
from pathlib import Path

from mbp.api.errors import ApiError
from mbp.backups.frames import FrameError, FrameReader
from mbp.backups.pipeline import PipelineResult, write_stream


class AgentDumpError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class AgentDumpProcess:
    """Same interface as DumpProcess: `run()` writes the file, `terminate()` stops it."""

    # No local process (BackupRunner.active_pids skips it).
    process = None

    def __init__(self, agent, payload: dict) -> None:
        self.agent = agent
        self.payload = payload
        self.terminated = False
        self._response = None
        self._lock = threading.Lock()

    def terminate(self) -> None:
        self.terminated = True
        with self._lock:
            response = self._response
        if response is not None:
            # Closing the connection makes the agent stop the dump.
            response.close()

    def run(
        self,
        temp_path: Path,
        compression: str,
        on_progress: Callable[[int], None],
        interval: float,
    ) -> PipelineResult:
        try:
            with self.agent.dump_stream(self.payload) as response:
                with self._lock:
                    self._response = response
                if self.terminated:
                    response.close()
                reader = FrameReader(response.iter_raw())
                try:
                    written = write_stream(
                        reader.data(), temp_path, compression, on_progress, interval
                    )
                except FrameError as exc:
                    raise AgentDumpError("agent_stream_broken", str(exc)) from exc
                except Exception:
                    if self.terminated:
                        return PipelineResult(1, "", 0, 0, "")
                    raise
        except ApiError as exc:
            if self.terminated:
                return PipelineResult(1, "", 0, 0, "")
            raise AgentDumpError(exc.code, exc.detail) from exc
        if reader.end is None:
            if self.terminated:
                return PipelineResult(1, "", 0, 0, "")
            raise AgentDumpError(
                "agent_stream_broken", "The connection to the server's agent was cut off."
            )
        return PipelineResult(
            returncode=reader.end["returncode"],
            stderr_tail=reader.end["stderr_tail"],
            **written,
        )
