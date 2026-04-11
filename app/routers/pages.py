from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MediaEntry

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


def _get_greeting_context() -> dict:
    """Generate time-aware greeting and content suggestion context."""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    is_weekend = weekday >= 5

    if hour < 12:
        time_of_day = "morning"
        greeting = "Good morning"
        if is_weekend:
            suggestion = "Perfect time to start a new book or catch up on a film."
            suggested_types = ["book", "movie"]
        else:
            suggestion = "How about a podcast or audiobook for your commute?"
            suggested_types = ["podcast", "book"]
    elif hour < 17:
        time_of_day = "afternoon"
        greeting = "Good afternoon"
        if is_weekend:
            suggestion = "Great day for a movie marathon or diving into a new book."
            suggested_types = ["movie", "book"]
        else:
            suggestion = "Need a break? Queue up something good for later."
            suggested_types = ["podcast", "tv"]
    else:
        time_of_day = "evening"
        greeting = "Good evening"
        if is_weekend:
            suggestion = "Settle in with a great show or lose yourself in a book."
            suggested_types = ["tv", "book", "movie"]
        else:
            suggestion = "Time to unwind. A great show or book awaits."
            suggested_types = ["tv", "book"]

    return {
        "greeting": greeting,
        "suggestion": suggestion,
        "time_of_day": time_of_day,
        "is_weekend": is_weekend,
        "suggested_types": suggested_types,
    }


@router.get("/")
async def home(request: Request, db: Session = Depends(get_db)):
    consuming = db.query(MediaEntry).filter(MediaEntry.status == "consuming").all()
    want_to_consume = db.query(MediaEntry).filter(MediaEntry.status == "want_to_consume").all()
    consumed = db.query(MediaEntry).filter(MediaEntry.status == "consumed").all()
    total = db.query(MediaEntry).count()

    # Group "want to consume" into swim lanes by type
    queue_by_type: dict[str, list] = {}
    type_order = ["movie", "tv", "book", "podcast"]
    for item in want_to_consume:
        queue_by_type.setdefault(item.media_type, []).append(item)

    # Profile stats
    genre_counts: dict[str, int] = {}
    ratings = []
    type_counts: dict[str, int] = {}
    for e in consumed + consuming + want_to_consume:
        type_counts[e.media_type] = type_counts.get(e.media_type, 0) + 1
        if e.rating:
            ratings.append(e.rating)
        if e.genres:
            for g in e.genres.split(","):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1

    top_genres = sorted(genre_counts, key=genre_counts.get, reverse=True)[:5]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None
    genres_explored = len(genre_counts)

    greeting_ctx = _get_greeting_context()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "consuming": consuming,
            "queue_by_type": queue_by_type,
            "type_order": type_order,
            "total": total,
            "total_consumed": len(consumed),
            "total_consuming": len(consuming),
            "total_queue": len(want_to_consume),
            "genres_explored": genres_explored,
            "top_genres": top_genres,
            "avg_rating": avg_rating,
            "type_counts": type_counts,
            **greeting_ctx,
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


@router.get("/import/goodreads")
async def goodreads_import_page(request: Request):
    return templates.TemplateResponse("goodreads_import.html", {"request": request})


@router.get("/media/{media_type}/{external_id}")
async def media_detail_page(request: Request, media_type: str, external_id: str):
    return templates.TemplateResponse(
        "media_detail.html",
        {"request": request, "media_type": media_type, "external_id": external_id},
    )
