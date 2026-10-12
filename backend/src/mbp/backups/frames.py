"""The framing of a dump streamed by an agent: data frames, then one end frame.

Each frame is a type byte, a 4-byte big-endian length and the payload. "D" frames carry
the dump's bytes; the "E" frame carries a JSON object with the exit code and the end of
the tool's stderr. A stream without its end frame was cut off.
"""

import json
import struct
from collections.abc import Iterable, Iterator

DATA = b"D"
END = b"E"
_HEADER = struct.Struct(">cI")
MAX_FRAME = 4 * 1024 * 1024


class FrameError(Exception):
    pass


def encode(kind: bytes, payload: bytes) -> bytes:
    return _HEADER.pack(kind, len(payload)) + payload


def end_frame(returncode: int, stderr_tail: str) -> bytes:
    body = {"returncode": returncode, "stderr_tail": stderr_tail}
    return encode(END, json.dumps(body).encode("utf-8"))


class FrameReader:
    """Reads frames from a byte stream: `data()` yields the dump, then `end` is set."""

    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = iter(stream)
        self._buffer = bytearray()
        self.end: dict | None = None

    def _fill(self, size: int) -> bool:
        while len(self._buffer) < size:
            chunk = next(self._stream, None)
            if chunk is None:
                return False
            self._buffer += chunk
        return True

    def data(self) -> Iterator[bytes]:
        while self.end is None:
            if not self._fill(_HEADER.size):
                if self._buffer:
                    raise FrameError("truncated frame header")
                return  # cut off between frames: no end frame
            kind, length = _HEADER.unpack(bytes(self._buffer[: _HEADER.size]))
            if length > MAX_FRAME or kind not in (DATA, END):
                raise FrameError("invalid frame")
            if not self._fill(_HEADER.size + length):
                raise FrameError("truncated frame")
            payload = bytes(self._buffer[_HEADER.size : _HEADER.size + length])
            del self._buffer[: _HEADER.size + length]
            if kind == DATA:
                yield payload
            else:
                try:
                    end = json.loads(payload)
                    self.end = {
                        "returncode": int(end["returncode"]),
                        "stderr_tail": str(end.get("stderr_tail") or ""),
                    }
                except (ValueError, KeyError, TypeError) as exc:
                    raise FrameError("invalid end frame") from exc
