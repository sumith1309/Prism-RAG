"""Login + /me endpoints.

Public: POST /api/auth/login
Gated:  GET  /api/auth/me  (bearer token)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.auth.dependencies import CurrentUser, get_current_user
from src.auth.jwt import create_access_token
from src.auth.security import verify_password
from src.core import models

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    level: int
    title: str


class MeResponse(BaseModel):
    username: str
    role: str
    level: int


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = models.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(user.id, user.username, user.role, user.level)
    return LoginResponse(
        access_token=token,
        username=user.username,
        role=user.role,
        level=user.level,
        title=user.title,
    )


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(username=user.username, role=user.role, level=user.level)
