from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MediaEntry

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/")
async def home(request: Request, db: Session = Depends(get_db)):
    consuming = db.query(MediaEntry).filter(MediaEntry.status == "consuming").all()
    want_to_consume = db.query(MediaEntry).filter(MediaEntry.status == "want_to_consume").all()
    total = db.query(MediaEntry).count()

    # Group "currently consuming" by media type
    consuming_grouped: dict[str, list] = {}
    type_labels = {"movie": "Watching", "tv": "Watching", "book": "Reading", "podcast": "Listening to"}
    for item in consuming:
        label = type_labels.get(item.media_type, "Enjoying")
        consuming_grouped.setdefault(label, []).append(item)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "consuming_grouped": consuming_grouped,
            "want_to_consume": want_to_consume,
            "total": total,
        },
    )


@router.get("/search")
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})


@router.get("/profile")
async def profile_page(request: Request):
    return templates.TemplateResponse("profile.html", {"request": request})


@router.get("/recommend")
async def recommend_page(request: Request):
    return templates.TemplateResponse("recommend.html", {"request": request})


@router.get("/bulk-add")
async def bulk_add_page(request: Request):
    return templates.TemplateResponse("bulk_add.html", {"request": request})


@router.get("/media/{media_type}/{external_id}")
async def media_detail_page(request: Request, media_type: str, external_id: str):
    return templates.TemplateResponse(
        "media_detail.html",
        {"request": request, "media_type": media_type, "external_id": external_id},
    )
