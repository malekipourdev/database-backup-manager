"""Adding, connecting and removing servers."""

import hmac
import logging
import secrets
import ssl

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbp.agent import PROTOCOL
from mbp.api.errors import ApiError
from mbp.config import get_settings
from mbp.containers.agent_client import AgentClient
from mbp.db import utcnow
from mbp.logging import register_secret
from mbp.models import ContainerSettings, Server
from mbp.repositories.server_repository import ServerRepository
from mbp.security import agent_auth, crypto
from mbp.servers.registry import get_registry, server_token

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10


def install_command(server: Server, token: str) -> str:
    """What to run on the server: its agent, with this server's token and port."""
    repo = get_settings().agent_repo_url
    return "\n".join(
        [
            f"git clone {repo} mbp-agent && cd mbp-agent",
            "cat > .env.agent <<EOF",
            f"MBP_AGENT_TOKEN={token}",
            f"MBP_AGENT_PORT={server.port}",
            "MBP_DOCKER_GID=$(stat -c %g /var/run/docker.sock)",
            "EOF",
            "sudo mkdir -p /opt/mbp-projects && sudo chown 10001:10001 /opt/mbp-projects",
            "docker compose -f docker-compose.agent.yml --env-file .env.agent up -d --build",
        ]
    )


class ServerService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ServerRepository(db)

    def get(self, server_id: int) -> Server:
        server = self.repo.get(server_id)
        if server is None:
            raise ApiError(404, "server_not_found")
        return server

    def _name_free(self, name: str, server: Server | None = None) -> None:
        other = self.repo.get_by_name(name)
        if other is not None and other is not server:
            raise ApiError(409, "name_taken", fields={"name": "name_taken"})

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ApiError(409, "name_taken", fields={"name": "name_taken"}) from exc

    def create(self, name: str, host: str, port: int, notes: str = "") -> tuple[Server, str]:
        self._name_free(name)
        token = agent_auth.new_token()
        register_secret(token)
        server = Server(
            name=name.strip(),
            name_normalized=name.strip().lower(),
            kind="remote",
            host=host.strip(),
            port=port,
            token_encrypted=crypto.encrypt(token),
            notes=notes,
        )
        self.db.add(server)
        self._commit()
        logger.info("Server %s added (%s:%s)", server.name, server.host, server.port)
        return server, token

    def update(self, server: Server, data: dict) -> Server:
        if "name" in data:
            self._name_free(data["name"], server)
            server.name = data["name"].strip()
            server.name_normalized = server.name.lower()
        if "notes" in data:
            server.notes = data["notes"]
        if not server.is_local:
            for field in ("host", "port"):
                if field in data and data[field] != getattr(server, field):
                    setattr(server, field, data[field].strip() if field == "host" else data[field])
        self._commit()
        return server

    def rotate_token(self, server: Server) -> str:
        """A new token; the agent must be set up with it and the server connected again."""
        if server.is_local:
            raise ApiError(409, "server_is_local")
        token = agent_auth.new_token()
        register_secret(token)
        server.token_encrypted = crypto.encrypt(token)
        self._unpair(server)
        self.db.commit()
        get_registry().forget(server.id)
        return token

    @staticmethod
    def _unpair(server: Server) -> None:
        server.cert_pem = None
        server.cert_fingerprint = None
        server.paired_at = None

    def delete(self, server: Server) -> None:
        if server.is_local:
            raise ApiError(409, "server_is_local")
        usage = self.repo.usage(server.id)
        if usage["projects"] or usage["instances"]:
            raise ApiError(409, "server_in_use", detail=f"{usage['projects']}:{usage['instances']}")
        settings = self.db.get(ContainerSettings, server.id)
        if settings is not None:
            self.db.delete(settings)
        self.db.delete(server)
        self.db.commit()
        get_registry().forget(server.id)
        logger.info("Server %s removed", server.name)

    # --- contact ---

    def connect(self, server: Server) -> Server:
        """Check the agent: for another server, prove it holds the token and pin its cert."""
        if server.is_local:
            return self.check(server)
        if not server.host or not server.port:
            raise ApiError(409, "server_not_connected")
        host, port, token = server.host, server.port, server_token(server)
        server_id = server.id
        self.db.commit()  # no transaction held during network calls
        try:
            pem = ssl.get_server_certificate((host, port), timeout=CONNECT_TIMEOUT)
        except (OSError, ssl.SSLError) as exc:
            self._record(server_id, False, "agent_unreachable")
            raise ApiError(503, "agent_unreachable") from exc
        fp = agent_auth.fingerprint(ssl.PEM_cert_to_DER_cert(pem))
        nonce = secrets.token_hex(16)
        client = AgentClient.remote(host, port, token, pem, timeout=CONNECT_TIMEOUT * 3)
        try:
            hello = client.hello(nonce)
        except ApiError as exc:
            self._record(server_id, False, exc.code)
            raise
        finally:
            client.close()
        if not hmac.compare_digest(str(hello.get("proof", "")), agent_auth.proof(token, nonce, fp)):
            self._record(server_id, False, "agent_proof_invalid")
            raise ApiError(502, "agent_proof_invalid")
        if int(hello.get("protocol") or 0) < PROTOCOL:
            self._record(server_id, False, "agent_outdated")
            raise ApiError(409, "agent_outdated")
        server = self.get(server_id)
        server.cert_pem = pem
        server.cert_fingerprint = fp
        server.paired_at = utcnow()
        server.agent_hostname = (hello.get("hostname") or None) and str(hello["hostname"])[:255]
        server.docker_version = (hello.get("docker_version") or None) and str(
            hello["docker_version"]
        )[:64]
        server.last_seen_at = utcnow()
        server.last_error = None
        self.db.commit()
        get_registry().forget(server_id)
        logger.info("Server %s connected (certificate %s)", server.name, fp[:16])
        return server

    def check(self, server: Server) -> Server:
        """Ask the agent for its info and record the outcome."""
        server_id = server.id
        agent = get_registry().for_server(server)
        self.db.commit()
        try:
            info = agent.info()
        except ApiError as exc:
            self._record(server_id, False, exc.code)
            raise
        self._record(server_id, True, None, info)
        return self.get(server_id)

    def _record(self, server_id: int, ok: bool, code: str | None, info: dict | None = None):
        record_contact(self.db, server_id, ok, code, info)


def record_contact(
    db: Session, server_id: int, ok: bool, code: str | None, info: dict | None = None
) -> None:
    server = db.get(Server, server_id)
    if server is None:
        return
    if ok:
        server.last_seen_at = utcnow()
        server.last_error = None
        docker = (info or {}).get("docker") or {}
        if docker.get("version"):
            server.docker_version = str(docker["version"])[:64]
        if docker.get("name"):
            server.agent_hostname = str(docker["name"])[:255]
    else:
        server.last_error = (code or "agent_error")[:64]
    db.commit()
