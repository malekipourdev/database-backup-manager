from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from mbp.api import auth, health, instances
from mbp.api.errors import register_error_handlers
from mbp.config import get_settings
from mbp.db import get_sessionmaker
from mbp.logging import configure_logging
from mbp.security import crypto
from mbp.security.sessions import require_csrf, require_session
from mbp.services.auth_service import bootstrap_admin

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with get_sessionmaker()() as db:
        bootstrap_admin(db, get_settings())
    yield


def create_app() -> FastAPI:
    configure_logging()
    crypto.validate_key()

    app = FastAPI(
        title="MySQL Backup Panel",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    register_error_handlers(app)

    # Unauthenticated: health check (no data) and login only. Everything else requires
    # a valid session and the CSRF header (Constitution Principle I).
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth.public_router, prefix=API_PREFIX)
    protected = [Depends(require_session), Depends(require_csrf)]
    app.include_router(auth.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(instances.router, prefix=API_PREFIX, dependencies=protected)
    return app


app = create_app()
