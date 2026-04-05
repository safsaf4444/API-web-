# backend/deps/auth.py

from typing import Callable

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


def require_role(role: str) -> Callable:
    """
    FastAPI dependency factory that enforces RBAC.

    Usage:
        current_user: User = Depends(require_role("trust_reviewer"))

    The user must be authenticated AND have the given role in the
    UserRole table (or be an admin, which satisfies any role check).
    """
    def _check(
        session: Session = Depends(get_session),
        current_user: User = Depends(get_current_user),
    ) -> User:
        from backend.models_trust import UserRole

        # Admin satisfies every role check
        is_admin = session.exec(
            select(UserRole)
            .where(UserRole.username == current_user.username)
            .where(UserRole.role == "admin")
        ).first()
        if is_admin:
            return current_user

        # Check for the specific role
        if role != "admin":
            has_role = session.exec(
                select(UserRole)
                .where(UserRole.username == current_user.username)
                .where(UserRole.role == role)
            ).first()
            if has_role:
                return current_user

        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' required.",
        )

    return _check
