import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DevicePairing, RefreshToken, User
from app.services.tokens import (
    ACCESS_TOKEN_TTL,
    REFRESH_TOKEN_TTL,
    generate_refresh_token,
    hash_token,
    issue_access_token,
)

router = APIRouter()

PAIRING_TTL = timedelta(minutes=15)
POLL_INTERVAL_SECONDS = 5


def _generate_user_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class DevicePollRequest(BaseModel):
    device_code: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/device/start")
def device_start(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    pairing = DevicePairing(
        device_code=secrets.token_urlsafe(32),
        user_code=_generate_user_code(),
        status="pending",
        expires_at=now + PAIRING_TTL,
    )
    db.add(pairing)
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    # Google OAuth rejects private IPs — rewrite to localhost for local dev
    verification_url = f"{base_url}/device"
    for private in ("192.168.", "10.", "172."):
        if private in verification_url:
            verification_url = "http://localhost:8000/device"
            break

    return {
        "device_code": pairing.device_code,
        "user_code": pairing.user_code,
        "verification_uri": verification_url,
        "expires_in": int(PAIRING_TTL.total_seconds()),
        "interval": POLL_INTERVAL_SECONDS,
    }


@router.post("/device/poll")
def device_poll(req: DevicePollRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    pairing = db.query(DevicePairing).filter(DevicePairing.device_code == req.device_code).first()

    if not pairing:
        raise HTTPException(status_code=400, detail="invalid_device_code")

    expires_at = pairing.expires_at if pairing.expires_at.tzinfo else pairing.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise HTTPException(status_code=400, detail="expired_token")

    if pairing.last_polled_at:
        last = pairing.last_polled_at if pairing.last_polled_at.tzinfo else pairing.last_polled_at.replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < POLL_INTERVAL_SECONDS:
            raise HTTPException(status_code=400, detail="slow_down")

    pairing.last_polled_at = now
    db.commit()

    if pairing.status == "pending":
        raise HTTPException(status_code=400, detail="authorization_pending")

    if pairing.status == "denied":
        raise HTTPException(status_code=400, detail="access_denied")

    if pairing.status != "approved" or not pairing.user_id:
        raise HTTPException(status_code=400, detail="invalid_device_code")

    access_token = issue_access_token(pairing.user_id)
    raw_refresh = generate_refresh_token()
    refresh_row = RefreshToken(
        user_id=pairing.user_id,
        token_hash=hash_token(raw_refresh),
        device_label="Apple TV",
        expires_at=now + REFRESH_TOKEN_TTL,
    )
    db.add(refresh_row)

    pairing.status = "consumed"
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
    }


@router.post("/auth/refresh")
def auth_refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    hashed = hash_token(req.refresh_token)
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hashed,
        RefreshToken.revoked_at.is_(None),
    ).first()

    if not row:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")

    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise HTTPException(status_code=401, detail="refresh_token_expired")

    row.revoked_at = now

    new_raw = generate_refresh_token()
    new_row = RefreshToken(
        user_id=row.user_id,
        token_hash=hash_token(new_raw),
        device_label=row.device_label,
        expires_at=now + REFRESH_TOKEN_TTL,
    )
    db.add(new_row)
    db.commit()

    return {
        "access_token": issue_access_token(row.user_id),
        "refresh_token": new_raw,
        "token_type": "bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
    }


@router.post("/auth/logout")
def auth_logout(req: RefreshRequest, db: Session = Depends(get_db)):
    hashed = hash_token(req.refresh_token)
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == hashed,
        RefreshToken.revoked_at.is_(None),
    ).first()
    if row:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}
