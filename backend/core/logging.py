from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def init_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger = logging.getLogger("api")
        req_id = request.headers.get("x-request-id") or str(uuid4())
        start = time.time()

        response = await call_next(request)

        ms = int((time.time() - start) * 1000)
        logger.info(
            "%s %s -> %s (%sms) req_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            ms,
            req_id,
        )
        response.headers["x-request-id"] = req_id
        response.headers["x-response-ms"] = str(ms)
        return response


def install_logging(app: FastAPI) -> None:
    init_logging()
    app.add_middleware(RequestLoggingMiddleware)