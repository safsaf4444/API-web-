from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import User
from backend.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserPublic,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserPublic)
def register(payload: RegisterRequest, session: Session = Depends(get_session)):
    existing = session.exec(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    user = User(
        username=payload.username.strip(),
        email=payload.email.strip().lower(),
        hashed_password=hash_password(payload.password),
    )

    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Username or email already exists")

    session.refresh(user)
    return UserPublic(id=user.id, username=user.username, email=user.email)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == payload.username)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(subject=user.username)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return UserPublic(id=current_user.id, username=current_user.username, email=current_user.email)


@router.get("/auth/token_status")
def token_status(
    token: str | None = Query(default=None, description="Optional token if not using Authorization header"),
    authorization: str | None = Header(default=None),
):
    """
    Accepts token from either:
    - Authorization: Bearer <token>   (preferred)
    - ?token=<token>                  (fallback for frontend)
    """
    raw_token: str | None = None

    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]

    if not raw_token and token:
        raw_token = token.strip()

    if not raw_token:
        raise HTTPException(status_code=401, detail="Missing token (Authorization header or ?token=)")

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