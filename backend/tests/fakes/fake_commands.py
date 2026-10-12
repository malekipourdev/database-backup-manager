"""A stand-in for the agent's CommandRunner: records commands and plays scripted output."""

import json
import threading


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail: dict[str, int] = {}  # command key -> exit code
        self.output: dict[str, list[str]] = {}
        self.ps = [{"Service": "web", "State": "running", "Health": "", "ExitCode": 0}]
        self.commit = ("a" * 40, "Add feature")
        self.gate: threading.Event | None = None
        self.lock = threading.Lock()

    @staticmethod
    def key(args: list[str]) -> str:
        if args[:2] == ["docker", "compose"]:
            # docker compose -p NAME [-f FILE] <subcommand> ...
            rest = args[2:]
            while rest and rest[0] in ("-p", "-f"):
                rest = rest[2:]
            return f"compose {rest[0]}" if rest else "compose"
        return " ".join(args[:2])

    def run(self, args, cwd, env, timeout, on_line) -> int:
        key = self.key(args)
        with self.lock:
            self.calls.append({"args": list(args), "cwd": str(cwd), "env": dict(env), "key": key})
        if self.gate is not None and key == "compose up":
            self.gate.wait(10)
        if key == "git init":
            (cwd / ".git").mkdir(exist_ok=True)
        if key == "git log":
            on_line(self.commit[0])
            on_line(self.commit[1])
        elif key == "compose ps":
            for item in self.ps:
                on_line(json.dumps(item))
        for line in self.output.get(key, []):
            on_line(line)
        return self.fail.get(key, 0)

    def called(self) -> list[str]:
        return [c["key"] for c in self.calls]
