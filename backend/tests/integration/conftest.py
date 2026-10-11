import os
from dataclasses import dataclass
from pathlib import Path

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

from mbp.config import get_settings

ROOT_PASSWORD = "Root-Pass-123"
IMAGES = {"mysql": "mysql:8.4", "mariadb": "mariadb:11.8"}


@dataclass(frozen=True)
class Server:
    kind: str
    image: str
    host: str
    port: int
    container_id: str

    def admin_connection(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user="root",
            password=ROOT_PASSWORD,
            autocommit=True,
        )

    def execute(self, *statements: str) -> None:
        conn = self.admin_connection()
        try:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
        finally:
            conn.close()


@pytest.fixture(scope="session", params=sorted(IMAGES), ids=sorted(IMAGES))
def server(request):
    kind = request.param
    container = MySqlContainer(IMAGES[kind], root_password=ROOT_PASSWORD, dbname="placeholder")
    with container:
        yield Server(
            kind=kind,
            image=IMAGES[kind],
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(3306)),
            container_id=container.get_wrapped_container().id,
        )


TOOLS = Path(__file__).resolve().parents[2] / ".tools"
REAL_MYSQLDUMP = os.environ.get("MBP_REAL_MYSQLDUMP_PATH", str(TOOLS / "mysqldump"))
REAL_MARIADB_DUMP = os.environ.get("MBP_REAL_MARIADB_DUMP_PATH", str(TOOLS / "mariadb-dump"))


@pytest.fixture
def real_tools(monkeypatch):
    for path in (REAL_MYSQLDUMP, REAL_MARIADB_DUMP):
        if not os.access(path, os.X_OK):
            pytest.skip(f"dump tool not found: {path} (run backend/scripts/install-dump-tools.sh)")
    settings = get_settings()
    monkeypatch.setattr(settings, "mysqldump_path", REAL_MYSQLDUMP)
    monkeypatch.setattr(settings, "mariadb_dump_path", REAL_MARIADB_DUMP)
