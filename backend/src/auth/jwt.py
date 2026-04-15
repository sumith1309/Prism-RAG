"""JWT create/verify using python-jose.

Tokens carry ``sub`` (username), ``uid`` (user id), ``role``, ``level``.
"""

from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from src.config import settings


def create_access_token(user_id: int, username: str, role: str, level: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": username,
        "uid": int(user_id),
        "role": role,
        "level": int(level),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.AUTH_TOKEN_TTL_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.AUTH_SECRET, algorithm=settings.AUTH_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.AUTH_SECRET, algorithms=[settings.AUTH_ALGORITHM])
    except JWTError:
        return None
