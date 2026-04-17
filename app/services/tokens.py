import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)


def issue_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
