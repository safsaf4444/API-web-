from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.core.config import settings


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_username(request: Request) -> Optional[str]:
    """Decode JWT from Authorization header — no DB hit, decode only."""
    try:
        from jose import JWTError, jwt
        from backend.auth import ALGORITHM, SECRET_KEY
        auth = request.headers.get("authorization", "")
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            payload = jwt.decode(parts[1], SECRET_KEY, algorithms=[ALGORITHM])
            return payload.get("sub")
    except Exception:
        pass
    return None


def _client_ip(request: Request) -> str:
    # Honour X-Forwarded-For if set by a trusted proxy (Vercel)
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_key(request: Request) -> str:
    """Prefer username over IP so shared NAT / load-balancer IPs don't cross-contaminate."""
    username = _extract_username(request)
    if username:
        return f"user:{username}"
    return f"ip:{_client_ip(request)}"


# ── Global sliding-window middleware ──────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    _SKIP_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/health", "/favicon.ico"}

    def __init__(self, app):
        super().__init__(app)
        self.hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        # Authenticated users are rate-limited per-route (see per_route_limit).
        # Global middleware only guards unauthenticated (guest/bot) traffic.
        if _extract_username(request):
            return await call_next(request)

        key = _rate_key(request)
        now = time.monotonic()
        window = settings.rate_limit_window_sec
        max_req = settings.rate_limit_max_requests

        q = self.hits[key]
        while q and q[0] <= now - window:
            q.popleft()

        if len(q) >= max_req:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many requests — please slow down and try again in a moment."}},
                headers={"Retry-After": str(window)},
            )
        q.append(now)
        return await call_next(request)


# ── Per-route rate limiter (Depends) ──────────────────────────────────────────

class _RouteStore:
    hits: dict[str, deque] = defaultdict(deque)

_route_store = _RouteStore()


def per_route_limit(max_calls: int, window_sec: int = 3600):
    """
    FastAPI dependency factory — per-route, per-user sliding window.

    Usage:
        @router.post("/ai/summarise")
        async def summarise(..., _rl=Depends(per_route_limit(20, 3600))):
    """
    async def _check(request: Request):
        if not settings.rate_limit_enabled:
            return
        key = f"{request.url.path}:{_rate_key(request)}"
        now = time.monotonic()
        q = _route_store.hits[key]
        while q and q[0] <= now - window_sec:
            q.popleft()
        if len(q) >= max_calls:
            mins = window_sec // 60
            period = f"{window_sec // 3600}h" if window_sec >= 3600 else f"{mins}min"
            raise HTTPException(
                status_code=429,
                detail=f"You've used all {max_calls} requests allowed per {period} for this feature. Try again later.",
                headers={"Retry-After": str(window_sec)},
            )
        q.append(now)
    return _check


# ── Auth brute-force protection ───────────────────────────────────────────────

class AuthRateLimiter:
    """
    Tracks failed authentication attempts per key (username:ip).
    Locks after max_failures within the window for lockout_sec.
    """
    def __init__(self, max_failures: int = 5, lockout_sec: int = 900):
        self.max_failures = max_failures
        self.lockout_sec = lockout_sec
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}

    def _clean(self, key: str) -> None:
        now = time.monotonic()
        self._failures[key] = [
            t for t in self._failures[key] if t > now - self.lockout_sec
        ]

    def check(self, identifier: str) -> None:
        """Raise 429 if the identifier is currently locked."""
        now = time.monotonic()
        locked = self._locked_until.get(identifier, 0)
        if now < locked:
            wait = int(locked - now)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {max(1, wait // 60)} minute(s).",
                headers={"Retry-After": str(wait)},
            )

    def record_failure(self, identifier: str) -> None:
        """Record a failed attempt; lock if threshold crossed."""
        now = time.monotonic()
        self._clean(identifier)
        self._failures[identifier].append(now)
        if len(self._failures[identifier]) >= self.max_failures:
            self._locked_until[identifier] = now + self.lockout_sec
            self._failures[identifier] = []

    def record_success(self, identifier: str) -> None:
        """Clear failure record on successful auth."""
        self._failures.pop(identifier, None)
        self._locked_until.pop(identifier, None)


# Singleton used by auth router
auth_limiter = AuthRateLimiter(max_failures=5, lockout_sec=900)


def install_rate_limit(app: FastAPI) -> None:
    app.add_middleware(RateLimitMiddleware)
