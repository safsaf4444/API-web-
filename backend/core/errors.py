from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _shape_error(status_code: int, code: str, message: str, details=None):
    payload = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        # preserve FastAPI status codes, standardize payload
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _shape_error(exc.status_code, "http_error", msg, details=exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        return _shape_error(422, "validation_error", "Invalid request", details=exc.errors())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception):
        # don’t leak internals to clients
        return _shape_error(500, "server_error", "Internal server error")
    