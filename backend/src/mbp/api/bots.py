from dataclasses import asdict

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.schemas import (
    BotAdminCreate,
    BotAdminOut,
    BotAdminUpdate,
    BotSettingsIn,
    BotSettingsOut,
    BotTestOut,
    LinkCodeOut,
    LinkCodeRequest,
)
from mbp.db import get_db
from mbp.models import BotSettings
from mbp.repositories.bot_repository import BotRepository
from mbp.services.bot_service import BotService, BotSettingsInput, check_platform

router = APIRouter(tags=["bots"])


def _manager(request: Request):
    return getattr(request.app.state, "bot_manager", None)


def _out(row: BotSettings, manager) -> BotSettingsOut:
    return BotSettingsOut(
        platform=row.platform,  # type: ignore[arg-type]
        enabled=row.enabled,
        has_token=bool(row.token_encrypted),
        api_base_url=row.api_base_url,
        proxy_url=row.proxy_url,
        allow_file_download=row.allow_file_download,
        max_file_mb=row.max_file_mb,
        bot_username=row.bot_username,
        running=bool(manager and manager.running(row.platform)),
        last_ok_at=row.last_ok_at,
        last_error=row.last_error,
    )


def _input(body: BotSettingsIn) -> BotSettingsInput:
    return BotSettingsInput(
        enabled=body.enabled,
        token=body.token.get_secret_value() if body.token else None,
        api_base_url=body.api_base_url,
        proxy_url=body.proxy_url,
        allow_file_download=body.allow_file_download,
        max_file_mb=body.max_file_mb,
    )


def _reload(request: Request, platform: str) -> None:
    manager = _manager(request)
    if manager is not None:
        manager.reload(platform)


@router.get("/bots", response_model=list[BotSettingsOut])
def list_bots(request: Request, db: Session = Depends(get_db)) -> list[BotSettingsOut]:
    return [_out(row, _manager(request)) for row in BotRepository(db).all_settings()]


@router.put("/bots/{platform}", response_model=BotSettingsOut)
def put_bot(
    platform: str, body: BotSettingsIn, request: Request, db: Session = Depends(get_db)
) -> BotSettingsOut:
    row = BotService(db).update_settings(platform, _input(body))
    _reload(request, platform)
    db.refresh(row)
    return _out(row, _manager(request))


@router.delete("/bots/{platform}/token", response_model=BotSettingsOut)
def delete_bot_token(
    platform: str, request: Request, db: Session = Depends(get_db)
) -> BotSettingsOut:
    row = BotService(db).clear_token(platform)
    _reload(request, platform)
    return _out(row, _manager(request))


@router.post("/bots/{platform}/test", response_model=BotTestOut)
def test_bot(platform: str, body: BotSettingsIn, db: Session = Depends(get_db)) -> BotTestOut:
    return BotTestOut(**asdict(BotService(db).test(platform, _input(body))))


@router.post("/bots/{platform}/link-codes", response_model=LinkCodeOut, status_code=201)
def create_link_code(
    platform: str, body: LinkCodeRequest, db: Session = Depends(get_db)
) -> LinkCodeOut:
    code, expires = BotService(db).create_link_code(platform, body.display_name)
    username = BotRepository(db).get_settings(platform).bot_username
    deep_link = None
    if username and platform == "telegram":
        deep_link = f"https://t.me/{username}?start={code}"
    return LinkCodeOut(code=code, expires_at=expires, bot_username=username, deep_link=deep_link)


@router.get("/bot-admins", response_model=list[BotAdminOut])
def list_bot_admins(db: Session = Depends(get_db)) -> list[BotAdminOut]:
    return [BotAdminOut.model_validate(a) for a in BotRepository(db).admins()]


@router.post("/bot-admins", response_model=BotAdminOut, status_code=201)
def create_bot_admin(body: BotAdminCreate, db: Session = Depends(get_db)) -> BotAdminOut:
    check_platform(body.platform)
    admin = BotService(db).add_admin(body.platform, body.user_id, body.display_name)
    return BotAdminOut.model_validate(admin)


@router.patch("/bot-admins/{admin_id}", response_model=BotAdminOut)
def update_bot_admin(
    admin_id: int, body: BotAdminUpdate, db: Session = Depends(get_db)
) -> BotAdminOut:
    admin = BotService(db).update_admin(admin_id, **body.model_dump(exclude_none=True))
    return BotAdminOut.model_validate(admin)


@router.delete("/bot-admins/{admin_id}", status_code=204)
def delete_bot_admin(admin_id: int, db: Session = Depends(get_db)) -> Response:
    BotService(db).delete_admin(admin_id)
    return Response(status_code=204)
