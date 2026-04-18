import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AllowedEmail, User

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@router.get("/login")
async def login(request: Request):
    """Redirect to Google OAuth consent screen."""
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    # Build redirect URI — force HTTPS in production (behind Cloud Run proxy)
    redirect_uri = str(request.url_for("auth_callback"))
    if "localhost" not in redirect_uri and "127.0.0.1" not in redirect_uri:
        redirect_uri = redirect_uri.replace("http://", "https://")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    """Handle Google OAuth callback."""
    # Verify state
    saved_state = request.session.pop("oauth_state", None)
    if not state or state != saved_state:
        return RedirectResponse("/?error=invalid_state")

    if not code:
        return RedirectResponse("/?error=no_code")

    redirect_uri = str(request.url_for("auth_callback"))
    if "localhost" not in redirect_uri and "127.0.0.1" not in redirect_uri:
        redirect_uri = redirect_uri.replace("http://", "https://")

    # Exchange code for token
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse("/?error=token_failed")
        tokens = token_resp.json()

        # Get user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            return RedirectResponse("/?error=userinfo_failed")
        userinfo = userinfo_resp.json()

    # Allowlist check — only runs when INVITE_ONLY=true
    email = userinfo.get("email", "").lower().strip()
    if settings.invite_only and email != settings.admin_email.lower().strip():
        allowed = db.query(AllowedEmail).filter(AllowedEmail.email == email).first()
        if not allowed:
            return RedirectResponse(f"/auth/access-denied?email={email}")

    # Find or create user
    google_id = userinfo["id"]
    is_brand_new = False
    try:
        user = db.query(User).filter(User.google_id == google_id).first()
        if not user:
            user = User(
                google_id=google_id,
                email=userinfo.get("email", ""),
                name=userinfo.get("name", ""),
                picture=userinfo.get("picture"),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            is_brand_new = True
        else:
            user.name = userinfo.get("name", user.name)
            user.picture = userinfo.get("picture", user.picture)
            db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse("/?error=db_failed")

    # Update last login
    from datetime import datetime
    user.last_login = datetime.utcnow()
    db.commit()

    # Set session
    request.session["user_id"] = user.id
    request.session["user_name"] = user.name
    request.session["user_picture"] = user.picture

    # If they came in via an invite link, redirect to accept it
    pending_invite = request.session.pop("pending_invite", None)
    if pending_invite:
        return RedirectResponse(f"/invite/{pending_invite}")

    # Brand new users go straight to onboarding — no chance to skip
    if is_brand_new:
        return RedirectResponse("/onboarding")

    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to welcome page."""
    request.session.clear()
    return RedirectResponse("/welcome")


@router.get("/access-denied")
async def access_denied(request: Request, email: str = ""):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse("access_denied.html", {"request": request, "email": email})
