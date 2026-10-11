from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.config import get_settings
from mbp.db import get_db
from mbp.models import AdminAccount
from mbp.repositories.admin_repository import AdminRepository
from mbp.repositories.session_repository import SessionRepository

COOKIE_NAME = "mbp_session"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "mbp"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def require_session(request: Request, db: Session = Depends(get_db)) -> AdminAccount:
    """Resolve the signed-in admin from the session cookie, or reject with 401."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise ApiError(401, "not_authenticated")
    sessions = SessionRepository(db)
    session = sessions.get_valid(token, get_settings().session_idle_minutes)
    if session is None:
        raise ApiError(401, "not_authenticated")
    admin = AdminRepository(db).get(session.admin_id)
    if admin is None:
        raise ApiError(401, "not_authenticated")
    if sessions.touch(session):
        db.commit()
    request.state.auth_session = session
    return admin


def require_csrf(request: Request) -> None:
    """Reject state-changing requests lacking the custom header (cross-site forms can't set it)."""
    if request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise ApiError(403, "csrf_failed")


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=get_settings().cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, samesite="strict", secure=get_settings().cookie_secure
    )
