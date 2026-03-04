# backend/deps/auth.py

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from backend.db import get_session
from backend.auth import decode_token
from backend.models import User


def get_current_user(
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User:
    """
    JWT Bearer dependency.
    Expects: Authorization: Bearer <token>
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    username = decode_token(parts[1])
    user = session.exec(select(User).where(User.username == username)).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
