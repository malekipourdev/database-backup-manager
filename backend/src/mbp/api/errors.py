import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Error(BaseModel):
    code: str
    detail: str | None = None
    fields: dict[str, str] | None = None


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        detail: str | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail
        self.fields = fields


def _body(code: str, detail: str | None = None, fields: dict[str, str] | None = None) -> dict:
    return Error(code=code, detail=detail, fields=fields).model_dump(exclude_none=True)


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.detail, exc.fields))


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Only field locations and error types are returned; submitted values (which may be
    # passwords) are never echoed back.
    fields: dict[str, str] = {}
    for error in exc.errors():
        loc = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path")]
        key = ".".join(loc) or "body"
        fields.setdefault(key, str(error.get("type", "invalid")))
    return JSONResponse(status_code=422, content=_body("validation_error", fields=fields))


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content=_body("internal_error"))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)
