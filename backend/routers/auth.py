from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.auth import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    hash_password,
    verify_password,
)
from backend.core.config import settings
from backend.core.rate_limit import auth_limiter, per_route_limit
from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import User
from backend.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)
from backend.services.email_service import (
    send_password_reset_email,
    send_verification_email,
)

logger = logging.getLogger("uvicorn")
router = APIRouter(tags=["auth"])

# ── In-memory token stores (replace with Redis in Phase 2 infra) ──────────────
# { token: {"username": str, "expires_at": datetime} }
_verification_tokens: dict[str, dict] = {}
_reset_tokens: dict[str, dict] = {}


def _make_token() -> str:
    return secrets.token_urlsafe(32)


def _purge_expired(store: dict) -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in store.items() if v["expires_at"] < now]
    for k in expired:
        del store[k]


# ── Registration ──────────────────────────────────────────────────────────────

@router.post("/auth/register", response_model=UserPublic)
def register(
    request: Request,
    payload: RegisterRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _rl=Depends(per_route_limit(10, 3600)),
):
    existing = session.exec(
        select(User).where(
            (User.username == payload.username) | (User.email == payload.email.strip().lower())
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    user = User(
        username=payload.username.strip(),
        email=payload.email.strip().lower(),
        hashed_password=hash_password(payload.password),
        is_verified=False,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Username or email already exists")

    session.refresh(user)

    # Send verification email in background
    token = _make_token()
    _verification_tokens[token] = {
        "username": user.username,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    background_tasks.add_task(
        send_verification_email, user.email, user.username, token
    )

    return UserPublic(id=user.id, username=user.username, email=user.email)


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenResponse)
def login(request: Request, payload: LoginRequest, session: Session = Depends(get_session)):
    from backend.core.rate_limit import _client_ip
    limiter_key = f"{payload.username}:{_client_ip(request)}"
    auth_limiter.check(limiter_key)

    user = session.exec(select(User).where(User.username == payload.username)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        auth_limiter.record_failure(limiter_key)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    auth_limiter.record_success(limiter_key)
    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token)


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return UserPublic(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
    )


# ── Token status ──────────────────────────────────────────────────────────────

@router.get("/auth/token_status")
def token_status(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    raw_token: str | None = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]
    if not raw_token and token:
        raw_token = token.strip()
    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = payload.get("exp")
        sub = payload.get("sub")
        now = datetime.now(timezone.utc).timestamp()
        exp_ts = float(exp) if exp is not None else None
        seconds_left = int(exp_ts - now) if exp_ts else None
        return {"valid": True, "sub": sub, "exp": exp_ts, "seconds_left": seconds_left}
    except JWTError:
        return {"valid": False}


# ── Token refresh ─────────────────────────────────────────────────────────────

@router.post("/auth/refresh", response_model=TokenResponse)
def refresh_token(current_user: User = Depends(get_current_user)):
    """Issue a fresh token for a still-valid session. No re-login needed."""
    new_token = create_access_token(subject=current_user.username)
    return TokenResponse(access_token=new_token)


# ── Password change ───────────────────────────────────────────────────────────

@router.post("/auth/change-password")
def change_password(
    payload: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Authenticated user changes their own password."""
    current = (payload.get("current_password") or "").strip()
    new_pw  = (payload.get("new_password") or "").strip()

    if not current or not new_pw:
        raise HTTPException(status_code=400, detail="current_password and new_password required")
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    if not verify_password(current, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    current_user.hashed_password = hash_password(new_pw)
    session.add(current_user)
    session.commit()
    return {"status": "ok", "message": "Password updated successfully"}


# ── Email verification ────────────────────────────────────────────────────────

@router.get("/auth/verify-email")
def verify_email(
    token: str = Query(...),
    session: Session = Depends(get_session),
):
    _purge_expired(_verification_tokens)
    entry = _verification_tokens.get(token)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")

    user = session.exec(
        select(User).where(User.username == entry["username"])
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_verified = True
    session.add(user)
    session.commit()
    del _verification_tokens[token]

    return {"status": "ok", "message": "Email verified. You can now log in."}


@router.post("/auth/resend-verification")
def resend_verification(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    if current_user.is_verified:
        return {"status": "ok", "message": "Already verified"}

    _purge_expired(_verification_tokens)
    token = _make_token()
    _verification_tokens[token] = {
        "username": current_user.username,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    background_tasks.add_task(
        send_verification_email, current_user.email, current_user.username, token
    )
    return {"status": "ok", "message": "Verification email sent"}


# ── Password reset ────────────────────────────────────────────────────────────

@router.post("/auth/forgot-password")
def forgot_password(
    payload: dict,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _rl=Depends(per_route_limit(5, 3600)),
):
    """Request a password reset email. Always returns 200 to prevent email enumeration."""
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        _purge_expired(_reset_tokens)
        token = _make_token()
        _reset_tokens[token] = {
            "username": user.username,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        background_tasks.add_task(
            send_password_reset_email, user.email, user.username, token
        )

    # Always return same response — don't reveal whether email exists
    return {"status": "ok", "message": "If that email exists, a reset link has been sent"}


@router.post("/auth/reset-password")
def reset_password(
    payload: dict,
    session: Session = Depends(get_session),
):
    token  = (payload.get("token") or "").strip()
    new_pw = (payload.get("new_password") or "").strip()

    if not token or not new_pw:
        raise HTTPException(status_code=400, detail="token and new_password required")
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    _purge_expired(_reset_tokens)
    entry = _reset_tokens.get(token)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user = session.exec(
        select(User).where(User.username == entry["username"])
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(new_pw)
    session.add(user)
    session.commit()
    del _reset_tokens[token]

    return {"status": "ok", "message": "Password reset. You can now log in."}


# ── Google OAuth ──────────────────────────────────────────────────────────────

@router.get("/auth/google")
def google_login():
    """Redirect user to Google OAuth consent screen."""
    if not settings.google_client_id:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)


@router.get("/auth/google/callback")
async def google_callback(
    code: str = Query(...),
    session: Session = Depends(get_session),
):
    """Handle Google OAuth callback — create or log in user, return JWT."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if token_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Google token exchange failed")

    google_tokens = token_res.json()
    access_token  = google_tokens.get("access_token")

    # Get user info from Google
    async with httpx.AsyncClient(timeout=15.0) as client:
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if user_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch Google user info")

    gdata    = user_res.json()
    email    = (gdata.get("email") or "").strip().lower()
    g_name   = gdata.get("name") or gdata.get("given_name") or email.split("@")[0]
    username = g_name.replace(" ", "_").lower()[:30]

    if not email:
        raise HTTPException(status_code=400, detail="No email returned from Google")

    # Find or create user
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        # Ensure unique username
        base = username
        suffix = 0
        while session.exec(select(User).where(User.username == username)).first():
            suffix += 1
            username = f"{base}_{suffix}"

        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),  # unusable password
            is_verified=True,  # Google emails are pre-verified
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info(f"New Google user created: {user.username}")

    jwt_token = create_access_token(subject=user.username)

    # Redirect to frontend with token
    from fastapi.responses import RedirectResponse
    redirect_url = f"{settings.frontend_url}/login.html?token={jwt_token}&username={user.username}"
    return RedirectResponse(redirect_url)