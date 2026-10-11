from dataclasses import dataclass

import pymysql
import pytest
from testcontainers.mysql import MySqlContainer

ROOT_PASSWORD = "Root-Pass-123"
IMAGES = {"mysql": "mysql:8.4", "mariadb": "mariadb:11.8"}


@dataclass(frozen=True)
class Server:
    kind: str
    image: str
    host: str
    port: int

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
        )
