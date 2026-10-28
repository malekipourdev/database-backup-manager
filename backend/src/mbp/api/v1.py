"""The external API, /api/v1: the panel's own endpoints, authenticated with API keys.

The same routers as the dashboard's /api are included a second time under /api/v1, so every
feature is in both and stays so. Only the authentication differs: a key (with scopes)
instead of the session cookie and CSRF header. Signing in, two-factor setup and the API
keys themselves stay dashboard-only.
"""

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from mbp.api import health
from mbp.api.schemas import ApiCatalog, ApiMe
from mbp.apiaccess.keys import require_api_key
from mbp.apiaccess.middleware import V1_PREFIX
from mbp.apiaccess.openapi import SELF_TAG, TITLE, catalog, get_spec
from mbp.models import ApiKey

OPENAPI_PATH = f"{V1_PREFIX}/openapi.json"

meta = APIRouter(tags=[SELF_TAG])
docs = APIRouter(include_in_schema=False)


@meta.get("/me", response_model=ApiMe)
def me(request: Request, key: ApiKey = Depends(require_api_key)) -> ApiMe:
    """The key making the request: its scopes, limits, and the admin it acts as."""
    return ApiMe(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=key.scopes,
        allowed_ips=key.allowed_ips,
        rate_limit=key.rate_limit,
        expires_at=key.expires_at,
        admin=request.state.api_admin.username,
        ip=request.state.api_ip,
    )


@meta.get("/catalog", response_model=ApiCatalog)
def get_catalog(request: Request, _: ApiKey = Depends(require_api_key)) -> dict:
    """Every area with its number of read and write operations, every scope, every event."""
    return catalog(request.app)


@docs.get("/openapi.json")
def openapi(request: Request) -> JSONResponse:
    return JSONResponse(get_spec(request.app))


@docs.get("/docs")
def swagger() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=OPENAPI_PATH,
        title=f"{TITLE} — Swagger UI",
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
    )


@docs.get("/redoc")
def redoc() -> HTMLResponse:
    return get_redoc_html(openapi_url=OPENAPI_PATH, title=TITLE)


def include_v1(app: FastAPI, routers: list[APIRouter]) -> None:
    v1 = APIRouter(prefix=V1_PREFIX)
    v1.include_router(docs)
    v1.include_router(health.router)
    v1.include_router(meta)
    for router in routers:
        v1.include_router(router, dependencies=[Depends(require_api_key)])
    app.include_router(v1)
