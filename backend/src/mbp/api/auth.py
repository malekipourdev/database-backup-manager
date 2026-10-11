from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from mbp.api.schemas import (
    CodeConfirm,
    LoginRequest,
    LoginResponse,
    Me,
    PasswordAndCode,
    PasswordConfirm,
    RecoveryCodes,
    SecondFactorRequest,
    TwoFactorSetup,
    TwoFactorStatus,
)
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
from mbp.services.two_factor_service import TwoFactorService

# Login (both steps) is the only unauthenticated action; it still requires the CSRF header.
public_router = APIRouter(tags=["auth"], dependencies=[Depends(require_csrf)])
router = APIRouter(tags=["auth"])


@public_router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
    result = AuthService(db, get_settings()).login(body.username, body.password.get_secret_value())
    if result.challenge is not None:
        return LoginResponse(
            username=result.admin.username, two_factor_required=True, challenge=result.challenge
        )
    set_session_cookie(response, result.token or "")
    return LoginResponse(username=result.admin.username)


@public_router.post("/auth/login/2fa", response_model=LoginResponse)
def login_second_factor(
    body: SecondFactorRequest, response: Response, db: Session = Depends(get_db)
) -> LoginResponse:
    result = AuthService(db, get_settings()).login_second_factor(
        body.challenge, body.code.get_secret_value()
    )
    set_session_cookie(response, result.token or "")
    return LoginResponse(username=result.admin.username)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    AuthService(db, get_settings()).logout(request.state.auth_session)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/auth/me", response_model=Me)
def me(admin: AdminAccount = Depends(require_session)) -> Me:
    return Me(username=admin.username, two_factor_enabled=admin.totp_enabled)


@router.get("/auth/2fa", response_model=TwoFactorStatus)
def two_factor_status(
    admin: AdminAccount = Depends(require_session), db: Session = Depends(get_db)
) -> TwoFactorStatus:
    enabled, left = TwoFactorService(db, admin).status()
    return TwoFactorStatus(enabled=enabled, recovery_codes_left=left)


@router.post("/auth/2fa/setup", response_model=TwoFactorSetup)
def two_factor_setup(
    body: PasswordConfirm,
    admin: AdminAccount = Depends(require_session),
    db: Session = Depends(get_db),
) -> TwoFactorSetup:
    info = TwoFactorService(db, admin).start_setup(body.password.get_secret_value())
    return TwoFactorSetup(secret=info.secret, otpauth_uri=info.otpauth_uri, qr_svg=info.qr_svg)


@router.post("/auth/2fa/enable", response_model=RecoveryCodes)
def two_factor_enable(
    body: CodeConfirm,
    request: Request,
    admin: AdminAccount = Depends(require_session),
    db: Session = Depends(get_db),
) -> RecoveryCodes:
    codes = TwoFactorService(db, admin).enable(
        body.code.get_secret_value(), request.state.auth_session
    )
    return RecoveryCodes(recovery_codes=codes)


@router.post("/auth/2fa/disable", status_code=204)
def two_factor_disable(
    body: PasswordAndCode,
    request: Request,
    admin: AdminAccount = Depends(require_session),
    db: Session = Depends(get_db),
) -> Response:
    TwoFactorService(db, admin).disable(
        body.password.get_secret_value(),
        body.code.get_secret_value(),
        request.state.auth_session,
    )
    return Response(status_code=204)


@router.post("/auth/2fa/recovery-codes", response_model=RecoveryCodes)
def two_factor_recovery_codes(
    body: PasswordAndCode,
    admin: AdminAccount = Depends(require_session),
    db: Session = Depends(get_db),
) -> RecoveryCodes:
    codes = TwoFactorService(db, admin).regenerate_recovery_codes(
        body.password.get_secret_value(), body.code.get_secret_value()
    )
    return RecoveryCodes(recovery_codes=codes)
