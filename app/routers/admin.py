from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.config import settings
from app.database import get_db
from app.models import AllowedEmail, Collection, CollectionItem, DismissedItem, MediaEntry, Recommendation, User, UserPreferences

router = APIRouter()


@router.get("/users")
async def admin_users(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="app/templates")
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    allowed = db.query(AllowedEmail).order_by(AllowedEmail.created_at.desc()).all()
    all_users = db.query(User).order_by(User.created_at.desc()).all()

    # Build per-user stats
    from sqlalchemy import func as sqlfunc
    from app.services.taste_quiz_scoring import load_quiz_results
    user_stats = {}
    for u in all_users:
        total = db.query(MediaEntry).filter(MediaEntry.user_id == u.id).count()
        rated = db.query(MediaEntry).filter(MediaEntry.user_id == u.id, MediaEntry.rating.isnot(None)).count()
        qr = load_quiz_results(db, u.id)
        quizzes = sum(1 for t in ("movies", "tv", "books") if qr and qr.get(t, {}).get("profiles"))
        user_stats[u.id] = {"total": total, "rated": rated, "quizzes": quizzes}

    # Find or create test user
    test_user = db.query(User).filter(User.email == "test@nextup.local").first()
    if not test_user:
        test_user = User(google_id="test_user_000", email="test@nextup.local", name="Test User", picture=None)
        db.add(test_user)
        db.commit()
        db.refresh(test_user)

    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "user": user,
        "allowed": allowed,
        "all_users": all_users,
        "user_stats": user_stats,
        "invite_only": settings.invite_only,
        "test_user_id": test_user.id,
    })


@router.post("/users/add")
async def admin_add_user(
    request: Request,
    email: str = Form(...),
    note: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
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


@router.post("/users/delete")
async def admin_delete_user(
    request: Request,
    user_id: int = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Delete a user and all their data. Admin only. Cannot delete yourself."""
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    if user_id == user.id:
        return RedirectResponse("/admin/users", status_code=303)

    # Delete all user data in dependency order
    collection_ids = [c.id for c in db.query(Collection).filter(Collection.user_id == user_id).all()]
    if collection_ids:
        db.query(CollectionItem).filter(CollectionItem.collection_id.in_(collection_ids)).delete(synchronize_session=False)
    db.query(Collection).filter(Collection.user_id == user_id).delete()
    db.query(DismissedItem).filter(DismissedItem.user_id == user_id).delete()
    db.query(Recommendation).filter(Recommendation.user_id == user_id).delete()
    db.query(UserPreferences).filter(UserPreferences.user_id == user_id).delete()
    db.query(MediaEntry).filter(MediaEntry.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/impersonate-and-redirect")
async def admin_impersonate_redirect(
    request: Request,
    user_id: int = Form(...),
    redirect_to: str = Form("/"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Switch to a user and redirect to a specific page. Used by testing tools."""
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/admin/users", status_code=303)
    if "real_user_id" not in request.session:
        request.session["real_user_id"] = user.id
    request.session["user_id"] = target.id
    request.session["user_name"] = target.name
    request.session["user_picture"] = target.picture
    return RedirectResponse(redirect_to, status_code=303)


@router.post("/impersonate")
async def admin_impersonate(
    request: Request,
    user_id: int = Form(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Switch session to another user. Admin only. Stores original user
    so you can switch back."""
    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        return RedirectResponse("/")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse("/admin/users", status_code=303)
    # Save the real admin ID so we can switch back
    if "real_user_id" not in request.session:
        request.session["real_user_id"] = user.id
    request.session["user_id"] = target.id
    request.session["user_name"] = target.name
    request.session["user_picture"] = target.picture
    return RedirectResponse("/", status_code=303)


@router.post("/stop-impersonating")
async def admin_stop_impersonating(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Switch back to the real admin account."""
    real_id = request.session.pop("real_user_id", None)
    if not real_id:
        return RedirectResponse("/")
    real_user = db.query(User).filter(User.id == real_id).first()
    if not real_user:
        return RedirectResponse("/")
    request.session["user_id"] = real_user.id
    request.session["user_name"] = real_user.name
    request.session["user_picture"] = real_user.picture
    return RedirectResponse("/admin/users", status_code=303)
