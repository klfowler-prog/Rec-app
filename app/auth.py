"""Authentication dependency — gets the current user from the session or bearer token."""

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.services.tokens import verify_access_token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Get the current logged-in user, or None if not logged in."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        user_id = verify_access_token(auth_header[7:])
        if user_id:
            return db.query(User).filter(User.id == user_id).first()
        return None

    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Get the current user, or redirect to login if not authenticated."""
    user = get_current_user(request, db)
    if not user:
        raise _LoginRequired()
    return user


class _LoginRequired(Exception):
    pass
