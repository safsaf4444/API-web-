from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.hits = defaultdict(deque)  # ip -> deque[timestamps]

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # allow health/root without limiting if you want
        if request.url.path in {"/", "/docs", "/openapi.json"}:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()
        window = settings.rate_limit_window_sec
        max_req = settings.rate_limit_max_requests

        q = self.hits[ip]
        # drop old hits
        while q and q[0] <= now - window:
            q.popleft()

        if len(q) >= max_req:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many requests. Try again soon."}},
            )

        q.append(now)
        return await call_next(request)


def install_rate_limit(app: FastAPI) -> None:
    app.add_middleware(RateLimitMiddleware)