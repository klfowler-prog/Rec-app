from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import MediaEntry, User

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["admin_email"] = __import__("app.config", fromlist=["settings"]).settings.admin_email.lower()
router = APIRouter()


def _get_greeting_context(user_name: str) -> dict:
    """Generate time-aware greeting and content suggestion context."""
    now = datetime.now(ZoneInfo("America/New_York"))
    hour = now.hour
    weekday = now.weekday()
    is_weekend = weekday >= 5
    first_name = user_name.split()[0] if user_name else ""

    if hour < 12:
        time_of_day = "morning"
        greeting = f"Good morning, {first_name}"
        if is_weekend:
            suggestion = "Perfect time to start a new book or catch up on a film."
            suggested_types = ["book", "movie"]
        else:
            suggestion = "How about a podcast or audiobook for your commute?"
            suggested_types = ["podcast", "book"]
    elif hour < 17:
        time_of_day = "afternoon"
        greeting = f"Good afternoon, {first_name}"
        if is_weekend:
            suggestion = "Great day for a movie marathon or diving into a new book."
            suggested_types = ["movie", "book"]
        else:
            suggestion = "Need a break? Queue up something good for later."
            suggested_types = ["podcast", "tv"]
    else:
        time_of_day = "evening"
        greeting = f"Good evening, {first_name}"
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
async def home(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    # Light query — the new home page is almost entirely client-rendered
    # from /api/media/home/right-now, /api/media/home-bundle, and
    # /api/media/best-bet/*. The server only needs to know how many
    # entries the user has so we can pick between the empty state, the
    # new-user welcome modal, and the fully populated layout.
    total = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).count()

    greeting_ctx = _get_greeting_context(user.name)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "total": total,
            "is_new_user": total < 5,
            **greeting_ctx,
        },
    )


@router.get("/search")
async def search_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("search.html", {"request": request, "user": user})


@router.get("/profile")
async def profile_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})


@router.get("/profile/{media_type}")
async def profile_type_page(request: Request, media_type: str, user: User = Depends(require_user)):
    """Per-media-type library page. Top to bottom:
      1. Currently [watching/reading/listening]
      2. Your best bet (anchor-based hero rec)
      3. New you might like (new releases — skipped for podcasts)
      4. Your queue (You saved + We suggest)
      5. Your library (seen / followed / read / listened to)
    """
    if media_type not in ("movies", "tv", "books", "podcasts"):
        raise HTTPException(status_code=404, detail="Unknown media type")
    internal_type = {"movies": "movie", "tv": "tv", "books": "book", "podcasts": "podcast"}[media_type]
    type_label = {"movies": "Movies", "tv": "TV Shows", "books": "Books", "podcasts": "Podcasts"}[media_type]

    # Per-type copy — the library label matters because you don't
    # really "finish" a TV show or a podcast the way you finish a
    # movie or a book, but the user has still engaged with it.
    LABELS = {
        "movie": {
            "currently_heading": "Now watching",
            "currently_blurb": "Movies you're in the middle of.",
            "library_heading": "Movies you've seen",
            "library_blurb": "Everything you've watched in this category.",
            "currently_verb": "watching",
            "show_new_releases": True,
        },
        "tv": {
            "currently_heading": "Currently watching",
            "currently_blurb": "Shows you're actively in the middle of.",
            "library_heading": "Shows you follow",
            "library_blurb": "Shows you know and engage with — finished or ongoing.",
            "currently_verb": "watching",
            "show_new_releases": True,
        },
        "book": {
            "currently_heading": "Currently reading",
            "currently_blurb": "Books you're in the middle of.",
            "library_heading": "Books you've read",
            "library_blurb": "Everything you've read in this category.",
            "currently_verb": "reading",
            "show_new_releases": True,
        },
        "podcast": {
            "currently_heading": "Currently listening",
            "currently_blurb": "Podcasts you're actively listening to.",
            "library_heading": "Podcasts you listen to",
            "library_blurb": "Shows you know and engage with — ongoing or completed.",
            "currently_verb": "listening to",
            # iTunes top-podcasts feed isn't really a "new" signal —
            # skip the new-releases section on the podcast page.
            "show_new_releases": False,
        },
    }[internal_type]

    return templates.TemplateResponse(
        "profile_type.html",
        {
            "request": request,
            "user": user,
            "media_type": internal_type,
            "media_type_slug": media_type,
            "type_label": type_label,
            **LABELS,
        },
    )


@router.get("/taste")
async def taste_dna_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Taste DNA page. Loads the user's saved quiz results so the
    template can decide whether to show the new-user quiz prompts at
    the top or tuck them into a secondary 'retake' section at the
    bottom."""
    from app.services.taste_quiz_scoring import load_quiz_results

    quiz_results = load_quiz_results(db, user.id)
    quiz_status = {
        "movies": bool(quiz_results.get("movies", {}).get("profiles")) if quiz_results else False,
        "tv":     bool(quiz_results.get("tv", {}).get("profiles")) if quiz_results else False,
        "books":  bool(quiz_results.get("books", {}).get("profiles")) if quiz_results else False,
    }
    quiz_status["completed_count"] = sum(1 for v in (quiz_status["movies"], quiz_status["tv"], quiz_status["books"]) if v)
    quiz_status["total"] = 3
    return templates.TemplateResponse(
        "taste_dna.html",
        {"request": request, "user": user, "quiz_status": quiz_status},
    )


@router.get("/collections")
async def collections_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("collections.html", {"request": request, "user": user})


@router.get("/collections/{collection_id}")
async def collection_detail_page(request: Request, collection_id: int, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        "collection_detail.html",
        {"request": request, "user": user, "collection_id": collection_id},
    )


@router.get("/together")
async def together_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("together.html", {"request": request, "user": user})


# Activity-context chip slugs on the home page. Each resolves to a
# concrete mood query so the existing /recommend page (which already
# reads ?mood=) can take it from there — no changes required on the
# recommend side. Keep this dict in sync with the chip row in index.html.
_CONTEXT_TO_MOOD = {
    "walking_the_dog": "Suggest a podcast I could listen to while walking the dog — 30-60 minutes, conversational or narrative, something I can drop in and out of.",
    "tonight_binge":   "Recommend a TV show I can binge tonight — propulsive, 1-2 hour episodes, an ending that earns the next episode.",
    "wind_down":       "Suggest something to wind down with before bed — a low-stakes book or gentle TV, written or shot with care, slow my pulse.",
    "background_work": "Recommend something I can have on in the background while I work — familiar or conversational, doesn't demand my attention but rewards it when I lean in.",
    "weekend_binge": "Recommend something for a weekend stretch — the kind of thing that pulls you forward and makes time disappear. Could be a series, a book, a film, a podcast run — whatever fits this person's taste. The quality that matters is bingeability: you finish one part and immediately want the next. Not about length or format, about that feeling of being completely inside something.",
    "quick_escape":    "Recommend a quick escape — a fun movie or short-form TV, 15-90 minutes, something to get me out of my own head.",
}


@router.get("/discover")
async def discover_page(
    request: Request,
    user: User = Depends(require_user),
    context: str | None = None,
):
    """Single 'find me something' surface. Replaces the old /recommend page
    and absorbs the activity chips, Mad Lib, Best Bets, and For Your Day
    themes that previously lived on Home. Accepts an optional ?context=<slug>
    from a chip click and redirects to the same page with a prewritten
    mood query, so the inline chat (which auto-sends from ?mood=) takes
    over."""
    if context and context in _CONTEXT_TO_MOOD:
        from urllib.parse import urlencode

        target = "/discover?" + urlencode({"mood": _CONTEXT_TO_MOOD[context]})
        return RedirectResponse(url=target, status_code=303)
    return templates.TemplateResponse("discover.html", {"request": request, "user": user})


@router.get("/recommend")
async def recommend_page(request: Request, user: User = Depends(require_user)):
    """Legacy redirect — /recommend folded into /discover in the Phase B1
    rebuild. We preserve the query string so old chip and mood deep-links
    keep working."""
    qs = request.url.query
    target = "/discover" + (f"?{qs}" if qs else "")
    return RedirectResponse(url=target, status_code=303)


@router.get("/bulk-add")
async def bulk_add_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("bulk_add.html", {"request": request, "user": user})


@router.get("/add")
async def add_media_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("add_media.html", {"request": request, "user": user})


@router.get("/import/goodreads")
async def goodreads_import_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("goodreads_import.html", {"request": request, "user": user})


@router.get("/import/netflix")
async def netflix_import_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("netflix_import.html", {"request": request, "user": user})


@router.get("/import/plex")
async def plex_import_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("plex_import.html", {"request": request, "user": user})


@router.get("/quick-start")
async def quick_start_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("quick_start.html", {"request": request, "user": user})


@router.get("/quick-start/movies")
async def quick_start_movies_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        "quick_start_quiz.html",
        {
            "request": request,
            "user": user,
            "quiz_slug": "movies",
            "quiz_title": "Movie taste quiz",
            "quiz_blurb": "20 films, one at a time. We'll learn how you engage with film — pace, tone, ambiguity, humor — and use it to sharpen your recommendations.",
            "item_label": "Film",
        },
    )


@router.get("/quick-start/tv")
async def quick_start_tv_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        "quick_start_quiz.html",
        {
            "request": request,
            "user": user,
            "quiz_slug": "tv",
            "quiz_title": "TV taste quiz",
            "quiz_blurb": "19 shows, one at a time. We'll learn how you engage with long-form TV — commitment to long arcs, tolerance for ambiguity, where you sit on irony — and use it to sharpen your recommendations.",
            "item_label": "Show",
        },
    )


@router.get("/quick-start/books")
async def quick_start_books_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        "quick_start_quiz.html",
        {
            "request": request,
            "user": user,
            "quiz_slug": "books",
            "quiz_title": "Book taste quiz",
            "quiz_blurb": "Two modules — 20 fiction titles, then 10 nonfiction. We'll learn how you read (prose vs plot, ideas vs feelings, how dark you can go) and figure out which module is really driving your taste.",
            "item_label": "Book",
        },
    )


@router.get("/media/{media_type}/{external_id}")
async def media_detail_page(request: Request, media_type: str, external_id: str, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        "media_detail.html",
        {"request": request, "user": user, "media_type": media_type, "external_id": external_id},
    )
