"""FastAPI dependencies for auth + role gating."""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from src.auth.jwt import decode_token


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str
    level: int


def get_current_user(authorization: Optional[str] = Header(default=None)) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(
        id=int(payload.get("uid", 0)),
        username=str(payload.get("sub", "")),
        role=str(payload.get("role", "")),
        level=int(payload.get("level", 0)),
    )


def require_level(min_level: int):
    """Dependency factory: enforce user.level >= min_level, else 403."""

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires clearance level {min_level}; you are level {user.level}.",
            )
        return user

    return _dep
