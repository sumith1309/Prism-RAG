"""Password hashing using bcrypt directly (passlib 1.7 is incompatible with bcrypt 4.x)."""

import bcrypt


def hash_password(password: str) -> str:
    # bcrypt operates on 72-byte passwords max; truncating matches common practice.
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except Exception:
        return False
