from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.schemas import LoginRequest, Me
from mbp.config import get_settings
from mbp.db import get_db
from mbp.models import AdminAccount
from mbp.security.sessions import (
    clear_session_cookie,
    require_csrf,
    require_session,
    set_session_cookie,
)
from mbp.services.auth_service import AuthService

# Login is the only unauthenticated action; it still requires the CSRF header.
public_router = APIRouter(tags=["auth"], dependencies=[Depends(require_csrf)])
router = APIRouter(tags=["auth"])


@public_router.post("/auth/login", response_model=Me)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> Me:
    admin, token = AuthService(db, get_settings()).login(
        body.username, body.password.get_secret_value()
    )
    set_session_cookie(response, token)
    return Me(username=admin.username)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    AuthService(db, get_settings()).logout(request.state.auth_session)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/auth/me", response_model=Me)
def me(admin: AdminAccount = Depends(require_session)) -> Me:
    return Me(username=admin.username)
