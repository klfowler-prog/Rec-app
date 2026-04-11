"""Authentication dependency — gets the current user from the session."""

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Get the current logged-in user, or None if not logged in."""
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
