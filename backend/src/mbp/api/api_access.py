"""Managing the external API from the panel: settings, keys and the request log.

Signed-in admins only: a key can never create, change or read keys (it could widen itself).
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.api.schemas import (
    ApiCatalog,
    ApiKeyCreate,
    ApiKeyOut,
    ApiKeySecret,
    ApiKeyUpdate,
    ApiRequestOut,
    ApiRequestPage,
    ApiSettingsIO,
    PasswordConfirm,
)
from mbp.apiaccess import scopes
from mbp.apiaccess.keys import SHOWN, generate_key, hash_key
from mbp.apiaccess.openapi import catalog
from mbp.apiaccess.service import cors_origins, get_api_settings
from mbp.db import get_db, utcnow
from mbp.models import AdminAccount, ApiKey, ApiRequestLog
from mbp.security.passwords import verify_password
from mbp.security.sessions import require_session

router = APIRouter(tags=["api-access"])


def _confirm(admin: AdminAccount, password: str) -> None:
    if not verify_password(admin.password_hash, password):
        raise ApiError(403, "wrong_password", fields={"password": "wrong_password"})


def _scopes(values: list[str]) -> list[str]:
    bad = scopes.unknown([v.strip() for v in values])
    if bad:
        raise ApiError(422, "validation_error", detail=", ".join(bad), fields={"scopes": "unknown"})
    return scopes.normalize([v.strip() for v in values])


def _key(db: Session, key_id: int) -> ApiKey:
    key = db.get(ApiKey, key_id)
    if key is None:
        raise ApiError(404, "api_key_not_found")
    return key


def _out(db: Session, keys: list[ApiKey]) -> list[ApiKeyOut]:
    since = utcnow() - timedelta(hours=24)
    rows = db.execute(
        select(
            ApiRequestLog.key_id,
            func.count(ApiRequestLog.id),
            func.sum(case((ApiRequestLog.status >= 400, 1), else_=0)),
        )
        .where(ApiRequestLog.created_at >= since)
        .group_by(ApiRequestLog.key_id)
    ).all()
    counts = {key_id: (int(n or 0), int(errors or 0)) for key_id, n, errors in rows}
    now = utcnow()
    out = []
    for key in keys:
        item = ApiKeyOut.model_validate(key)
        item.requests_24h, item.errors_24h = counts.get(key.id, (0, 0))
        item.expired = key.expires_at is not None and key.expires_at <= now
        out.append(item)
    return out


# --- settings and catalog ---


@router.get("/api-access/settings", response_model=ApiSettingsIO)
def get_settings_(db: Session = Depends(get_db)) -> ApiSettingsIO:
    row = get_api_settings(db)
    db.commit()
    return ApiSettingsIO(
        enabled=row.enabled,
        cors_origins=list(row.cors_origins or []),
        log_retention_days=row.log_retention_days,
    )


@router.put("/api-access/settings", response_model=ApiSettingsIO)
def put_settings(body: ApiSettingsIO, db: Session = Depends(get_db)) -> ApiSettingsIO:
    row = get_api_settings(db)
    row.enabled = body.enabled
    row.cors_origins = body.cors_origins
    row.log_retention_days = body.log_retention_days
    db.commit()
    cors_origins.forget()
    return body


@router.get("/api-access/catalog", response_model=ApiCatalog)
def get_catalog(request: Request) -> dict:
    return catalog(request.app)


# --- keys ---


@router.get("/api-access/keys", response_model=list[ApiKeyOut])
def list_keys(db: Session = Depends(get_db)) -> list[ApiKeyOut]:
    return _out(db, list(db.scalars(select(ApiKey).order_by(ApiKey.id))))


@router.post("/api-access/keys", response_model=ApiKeySecret, status_code=201)
def create_key(
    body: ApiKeyCreate,
    admin: AdminAccount = Depends(require_session),
    db: Session = Depends(get_db),
) -> ApiKeySecret:
    """Creates a key; the response holds the key itself, shown this once."""
    _confirm(admin, body.password.get_secret_value())
    secret = generate_key()
    key = ApiKey(
        name=body.name,
        prefix=secret[:SHOWN],
        secret_hash=hash_key(secret),
        scopes=_scopes(body.scopes),
        allowed_ips=body.allowed_ips,
        rate_limit=body.rate_limit,
        enabled=True,
        expires_at=body.expires_at,
        admin_id=admin.id,
        request_count=0,
        created_at=utcnow(),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return ApiKeySecret(key=_out(db, [key])[0], secret=secret)


@router.patch("/api-access/keys/{key_id}", response_model=ApiKeyOut)
def update_key(key_id: int, body: ApiKeyUpdate, db: Session = Depends(get_db)) -> ApiKeyOut:
    key = _key(db, key_id)
    if body.name is not None:
        key.name = body.name
    if body.scopes is not None:
        key.scopes = _scopes(body.scopes)
    if body.allowed_ips is not None:
        key.allowed_ips = body.allowed_ips
    if body.rate_limit is not None:
        key.rate_limit = body.rate_limit
    if "expires_at" in body.model_fields_set:
        key.expires_at = body.expires_at
    if body.enabled is not None:
        key.enabled = body.enabled
    db.commit()
    db.refresh(key)
    return _out(db, [key])[0]


@router.post("/api-access/keys/{key_id}/rotate", response_model=ApiKeySecret)
def rotate_key(
    key_id: int,
    body: PasswordConfirm,
    admin: AdminAccount = Depends(require_session),
    db: Session = Depends(get_db),
) -> ApiKeySecret:
    """A new secret for the key, same settings; the old secret stops working at once."""
    _confirm(admin, body.password.get_secret_value())
    key = _key(db, key_id)
    secret = generate_key()
    key.prefix = secret[:SHOWN]
    key.secret_hash = hash_key(secret)
    key.rotated_at = utcnow()
    db.commit()
    db.refresh(key)
    return ApiKeySecret(key=_out(db, [key])[0], secret=secret)


@router.delete("/api-access/keys/{key_id}", status_code=204)
def delete_key(key_id: int, db: Session = Depends(get_db)) -> Response:
    db.delete(_key(db, key_id))
    db.commit()
    return Response(status_code=204)


# --- request log ---


@router.get("/api-access/requests", response_model=ApiRequestPage)
def requests(
    key_id: int | None = Query(default=None, ge=1),
    errors: bool = False,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ApiRequestPage:
    """Requests made with keys, newest first; `errors` keeps refused and failed ones."""
    stmt = select(ApiRequestLog, ApiKey.name).join(ApiKey, ApiKey.id == ApiRequestLog.key_id)
    if key_id is not None:
        stmt = stmt.where(ApiRequestLog.key_id == key_id)
    if errors:
        stmt = stmt.where(ApiRequestLog.status >= 400)
    if before is not None:
        stmt = stmt.where(ApiRequestLog.id < before)
    rows = db.execute(stmt.order_by(ApiRequestLog.id.desc()).limit(limit + 1)).all()
    items = []
    for entry, name in rows[:limit]:
        item = ApiRequestOut.model_validate(entry)
        item.key_name = name
        items.append(item)
    more = len(rows) > limit
    return ApiRequestPage(items=items, next_before=items[-1].id if more and items else None)
