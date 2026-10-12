"""One agent client per server, built from the server's row and rebuilt when it changes."""

import hashlib
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from mbp.api.errors import ApiError
from mbp.config import Settings
from mbp.containers.agent_client import AgentClient
from mbp.logging import register_secret
from mbp.models import Server
from mbp.security import crypto

_registry: "AgentRegistry | None" = None


def set_registry(registry: "AgentRegistry | None") -> None:
    global _registry
    _registry = registry


def get_registry() -> "AgentRegistry":
    if _registry is None:
        raise ApiError(503, "agent_unreachable")
    return _registry


def server_token(server: Server) -> str:
    if not server.token_encrypted:
        raise ApiError(409, "server_not_connected")
    token = crypto.decrypt(server.token_encrypted)
    register_secret(token)
    return token


def _version(server: Server) -> str:
    raw = f"{server.host}|{server.port}|{server.cert_fingerprint}|{server.token_encrypted}"
    return hashlib.sha256(raw.encode()).hexdigest()


class AgentRegistry:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        local: Callable[[], AgentClient],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        # The local agent's client lives on app.state, so tests can swap it.
        self.local = local
        self._clients: dict[int, tuple[str, AgentClient]] = {}
        # Test hook: server id -> client, used instead of building one.
        self.overrides: dict[int, AgentClient] = {}
        self._lock = threading.Lock()

    def for_server(self, server: Server) -> AgentClient:
        if server.is_local:
            return self.local()
        if server.id in self.overrides:
            return self.overrides[server.id]
        if server.cert_pem is None or server.host is None or server.port is None:
            raise ApiError(409, "server_not_connected")
        version = _version(server)
        with self._lock:
            cached = self._clients.get(server.id)
            if cached is not None and cached[0] == version:
                return cached[1]
        client = AgentClient.remote(
            server.host,
            server.port,
            server_token(server),
            server.cert_pem,
            timeout=self.settings.agent_timeout_seconds,
        )
        with self._lock:
            old = self._clients.get(server.id)
            self._clients[server.id] = (version, client)
        if old is not None:
            old[1].close()
        return client

    def get(self, server_id: int) -> AgentClient:
        with self.session_factory() as db:
            server = db.get(Server, server_id)
            if server is None:
                raise ApiError(404, "server_not_found")
            return self.for_server(server)

    def forget(self, server_id: int) -> None:
        with self._lock:
            old = self._clients.pop(server_id, None)
        if old is not None:
            old[1].close()

    def close(self) -> None:
        with self._lock:
            clients = [client for _, client in self._clients.values()]
            self._clients.clear()
        for client in clients:
            client.close()
