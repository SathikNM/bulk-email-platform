"""RFC 7807 problem+json errors."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None, **extra):
        self.status, self.title, self.detail, self.extra = status, title, detail, extra


def NotFound(what: str = "Resource") -> AppError:  # noqa: N802
    return AppError(404, "Not found", f"{what} not found")


def Conflict(detail: str, **extra) -> AppError:  # noqa: N802
    return AppError(409, "Conflict", detail, **extra)


def BadRequest(detail: str, **extra) -> AppError:  # noqa: N802
    return AppError(400, "Bad request", detail, **extra)


def Forbidden(detail: str = "You do not have permission for this action") -> AppError:  # noqa: N802
    return AppError(403, "Forbidden", detail)


def _problem(status: int, title: str, detail=None, **extra) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status}
    if detail is not None:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _problem(exc.status, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        resp = _problem(exc.status_code, str(exc.detail) if exc.detail else "Error")
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
                  for e in exc.errors()]
        return _problem(422, "Validation error", "One or more fields are invalid", errors=errors)
