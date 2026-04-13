from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.config import settings
from app.database import get_db
from app.models import AllowedEmail, User

router = APIRouter()


@router.get("/users")
async def admin_users(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="app/templates")
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    allowed = db.query(AllowedEmail).order_by(AllowedEmail.created_at.desc()).all()
    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "user": user,
        "allowed": allowed,
        "invite_only": settings.invite_only,
    })


@router.post("/users/add")
async def admin_add_user(
    request: Request,
    email: str = Form(...),
    note: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from app.main import templates
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    email = email.lower().strip()
    if email and not db.query(AllowedEmail).filter(AllowedEmail.email == email).first():
        db.add(AllowedEmail(email=email, note=note.strip() or None))
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/remove")
async def admin_remove_user(
    request: Request,
    email: str = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    db.query(AllowedEmail).filter(AllowedEmail.email == email.lower().strip()).delete()
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)
