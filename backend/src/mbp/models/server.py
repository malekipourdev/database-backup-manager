from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class Server(Base):
    """A machine the panel manages through its agent: the panel's own, or another one.

    The local server's agent runs next to the panel (compose profile "containers"). Any other
    server runs docker-compose.agent.yml with this row's token, and is trusted by the
    certificate pinned when it was connected.
    """

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    # local | remote
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Fernet token of the agent's token; never returned after it is first shown, or logged.
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The agent's certificate, pinned on connect; NULL until the server is connected.
    cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    cert_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # The error code of the last failed contact; NULL after a successful one.
    last_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    docker_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    @property
    def is_local(self) -> bool:
        return self.kind == "local"

    @property
    def paired(self) -> bool:
        return self.is_local or self.cert_pem is not None
