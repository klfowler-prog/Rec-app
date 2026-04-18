from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import DevicePairing, MediaEntry, User

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["admin_email"] = __import__("app.config", fromlist=["settings"]).settings.admin_email.lower()
router = APIRouter()


def _get_greeting_context(user_name: str) -> dict:
    """Generate day-aware greeting and featured content mode.

    The hero greeting and the featured section below it are one cohesive
    experience — the text introduces whatever content rotates in that day:

      Thu evening – Sat: theaters (movies in theaters scored for you)
      Sunday:            wind_down (cozy pick for the night before the week)
      Mon – Thu daytime: weekday (quick pick — podcast, continue, or queue)
    """
    now = datetime.now(ZoneInfo("America/New_York"))
    hour = now.hour
    weekday = now.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    is_weekend = weekday >= 5
    first_name = user_name.split()[0] if user_name else ""
    day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weekday]

    # Determine featured content mode
    if (weekday == 3 and hour >= 17) or weekday in (4, 5):
        featured_mode = "theaters"
    elif weekday == 6:
        featured_mode = "wind_down"
    else:
        featured_mode = "weekday"

    # Time-of-day label
    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    else:
        time_of_day = "evening"

    # Greeting — conversational, like a friend asking what you're in the mood for.
    if featured_mode == "theaters":
        if weekday == 3:
            greeting = f"Feeling like a movie, {first_name}?"
            suggestion = "The weekend's here early. Here's what's playing."
        elif weekday == 4:
            if hour < 17:
                greeting = f"Feeling like a movie, {first_name}?"
                suggestion = "Here's what's worth seeing this weekend."
            else:
                greeting = f"Movie night, {first_name}?"
                suggestion = "Here's what's playing right now."
        else:  # Saturday
            if hour < 17:
                greeting = f"Feeling like a movie, {first_name}?"
                suggestion = "Here's what's in theaters this weekend."
            else:
                greeting = f"Still time for a movie, {first_name}"
                suggestion = "Here's what's playing tonight."
        suggested_types = ["movie"]
    elif featured_mode == "wind_down":
        if hour < 12:
            greeting = f"What sounds good, {first_name}?"
            suggestion = "Nowhere to be. A book, a show — whatever you're in the mood for."
            suggested_types = ["book", "tv"]
        elif hour < 17:
            greeting = f"What do you want to get into, {first_name}?"
            suggestion = "Here's something good for the rest of your day."
            suggested_types = ["tv", "book", "movie"]
        else:
            greeting = f"Time to wind down, {first_name}"
            suggestion = "One more good thing before the week starts."
            suggested_types = ["tv", "book", "podcast"]
    else:  # weekday
        if hour < 12:
            greeting = f"What are you listening to, {first_name}?"
            suggestion = "Something good for your morning."
            suggested_types = ["podcast", "book"]
        elif hour < 17:
            greeting = f"What do you want to watch tonight, {first_name}?"
            suggestion = "Queue up something good for later."
            suggested_types = ["podcast", "tv"]
        else:
            greeting = f"What do you want to watch tonight, {first_name}?"
            suggestion = "Here are a few picks for right now."
            suggested_types = ["tv", "book"]

    return {
        "greeting": greeting,
        "suggestion": suggestion,
        "featured_mode": featured_mode,
        "time_of_day": time_of_day,
        "is_weekend": is_weekend,
        "day_name": day_name,
        "suggested_types": suggested_types,
    }


@router.get("/share/{share_user_id}")
async def share_page(request: Request, share_user_id: int, db: Session = Depends(get_db)):
    """Public shareable Taste DNA page with Open Graph meta tags."""
    share_user = db.query(User).filter(User.id == share_user_id).first()
    if not share_user:
        return RedirectResponse("/welcome")
    first_name = share_user.name.split()[0] if share_user.name else "Someone"
    base_url = str(request.base_url).rstrip("/")
    if "localhost" not in base_url and "127.0.0.1" not in base_url:
        base_url = base_url.replace("http://", "https://")
    image_url = f"{base_url}/api/media/taste-dna/share-image?user_id={share_user_id}&layout=landscape"
    return templates.TemplateResponse("share_card_page.html", {
        "request": request,
        "share_user": share_user,
        "first_name": first_name,
        "image_url": image_url,
        "page_url": f"{base_url}/share/{share_user_id}",
    })


@router.get("/welcome")
async def welcome_page(request: Request):
    """Public landing page for unauthenticated users."""
    # If already logged in, send to onboarding (gate will pass them
    # through to home if they already have a taste profile)
    user_id = request.session.get("user_id")
    if user_id:
        return RedirectResponse("/onboarding")
    return templates.TemplateResponse("welcome.html", {"request": request})


@router.get("/device")
async def device_pair_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("device_pair.html", {
        "request": request,
        "user": user,
        "error": None,
        "success": False,
    })


@router.post("/device/approve")
async def device_approve(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from datetime import datetime, timezone

    form = await request.form()
    user_code = str(form.get("user_code", "")).strip().upper()

    now = datetime.now(timezone.utc)
    pairing = db.query(DevicePairing).filter(
        DevicePairing.user_code == user_code,
        DevicePairing.status == "pending",
    ).first()

    if not pairing:
        return templates.TemplateResponse("device_pair.html", {
            "request": request, "user": user,
            "error": "Code not found or expired. Check your TV and try again.",
            "success": False,
        })

    expires_at = pairing.expires_at if pairing.expires_at.tzinfo else pairing.expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        return templates.TemplateResponse("device_pair.html", {
            "request": request, "user": user,
            "error": "That code has expired. Start a new pairing on your TV.",
            "success": False,
        })

    pairing.user_id = user.id
    pairing.status = "approved"
    db.commit()

    return templates.TemplateResponse("device_pair.html", {
        "request": request, "user": user,
        "error": None,
        "success": True,
    })


@router.get("/")
async def home(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Home does two things: helps the user close the loop on what they
    just consumed (rate / status update), and inspires them with one pick
    they didn't know they wanted. Everything else (mood browse, themes,
    Mad Lib, chat) lives on /discover."""

    # Gate: redirect to onboarding until the user has enough taste signal
    # for the AI to produce meaningful recommendations. Minimum: 5 rated
    # items OR 1 completed quiz (which rates 8-12 items across taste axes).
    MIN_RATINGS_FOR_RECS = 5
    from app.services.taste_quiz_scoring import load_quiz_results as _lqr
    _rated_count = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)
    ).count()
    _quiz = _lqr(db, user.id)
    _has_quiz = any(
        (_quiz or {}).get(t, {}).get("profiles")
        for t in ("movies", "tv", "books")
    )
    if _rated_count < MIN_RATINGS_FOR_RECS and not _has_quiz:
        return RedirectResponse("/onboarding", status_code=302)

    total = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).count()

    # "Sharpen your recs" — a small batch of unrated consumed items.
    # We show 4 at a time (not every unrated item) so it feels like a
    # quick action, not homework. The total count lets us show "12 more
    # to rate" so the user knows there's a backlog without being
    # overwhelmed. We randomize so repeat visits surface different items.
    from sqlalchemy import func
    unrated_query = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id,
        MediaEntry.status == "consumed",
        MediaEntry.rating.is_(None),
    )
    unrated_total = unrated_query.count()
    unrated_batch = unrated_query.order_by(func.random()).limit(4).all() if unrated_total > 0 else []

    # Currently engaging — what the user is actively in the middle of
    currently = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.status == "consuming")
        .order_by(MediaEntry.updated_at.desc())
        .limit(6)
        .all()
    )

    # "Up next on your list" — sortable queue
    queue_sort = request.query_params.get("queue_sort", "predicted")
    # Load queue items — pull top items per type so the type filter is
    # useful even when one type dominates the predicted ratings.
    if queue_sort == "recent":
        _order = [MediaEntry.created_at.desc()]
    elif queue_sort == "title":
        _order = [MediaEntry.title.asc()]
    else:
        _order = [MediaEntry.predicted_rating.desc().nullslast(), MediaEntry.created_at.desc()]

    up_next: list[MediaEntry] = []
    seen_ids: set[int] = set()
    for mt in ("movie", "tv", "book", "podcast"):
        items = (
            db.query(MediaEntry)
            .filter(MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume", MediaEntry.media_type == mt)
            .order_by(*_order)
            .limit(12)
            .all()
        )
        for it in items:
            if it.id not in seen_ids:
                up_next.append(it)
                seen_ids.add(it.id)

    # Re-sort the merged list by the chosen order (no cap — JS handles visibility)
    if queue_sort == "recent":
        up_next.sort(key=lambda e: e.created_at or datetime.min, reverse=True)
    elif queue_sort == "title":
        up_next.sort(key=lambda e: (e.title or "").lower())
    else:
        up_next.sort(key=lambda e: (-(e.predicted_rating or 0), e.title or ""))

    # "Your best bet this week" — single hero card, one media type per
    # day. We rotate by day-of-year so each user sees movie / tv / book /
    # podcast over the course of a week and the page feels fresh on
    # repeat visits without re-querying the AI. The actual /api/media/
    # best-bet/<type> call is cached 7 days per (user, type), so the
    # page typically lands on a cached pick.
    rotation = ["movie", "tv", "book", "podcast"]
    best_bet_media_type = rotation[datetime.now(ZoneInfo("America/New_York")).timetuple().tm_yday % 4]

    greeting_ctx = _get_greeting_context(user.name)

    # --- Consolidated stats: one query for counts + averages -----------
    from sqlalchemy import func as sqlfunc, case, literal_column

    month_ago = datetime.utcnow() - timedelta(days=30)
    stats_row = db.query(
        sqlfunc.count().filter(MediaEntry.rating.isnot(None)).label("rated_count"),
        sqlfunc.count().filter(MediaEntry.status == "want_to_consume").label("queue_count"),
        sqlfunc.count().filter(MediaEntry.rating == 5).label("fives_count"),
        sqlfunc.count().filter(MediaEntry.rated_at >= month_ago).label("rated_this_month"),
        sqlfunc.avg(case((MediaEntry.rating.isnot(None), MediaEntry.rating))).label("avg_rating"),
    ).filter(MediaEntry.user_id == user.id).first()

    rated_count = stats_row.rated_count or 0
    queue_count = stats_row.queue_count or 0
    fives_count = stats_row.fives_count or 0
    rated_this_month = stats_row.rated_this_month or 0
    avg_rating = round(float(stats_row.avg_rating), 1) if stats_row.avg_rating else None

    # Type breakdown + per-type averages in one query
    type_rows = (
        db.query(
            MediaEntry.media_type,
            sqlfunc.count().label("cnt"),
            sqlfunc.avg(case((MediaEntry.rating.isnot(None), MediaEntry.rating))).label("avg_r"),
        )
        .filter(MediaEntry.user_id == user.id)
        .group_by(MediaEntry.media_type)
        .all()
    )
    type_counts = {r.media_type: r.cnt for r in type_rows}
    type_avgs = {r.media_type: round(float(r.avg_r), 2) for r in type_rows if r.avg_r}

    # Taste comparison from per-type averages
    taste_comparison = ""
    if len(type_avgs) >= 2:
        highest = max(type_avgs, key=type_avgs.get)
        lowest = min(type_avgs, key=type_avgs.get)
        labels = {"movie": "movies", "tv": "TV shows", "book": "books", "podcast": "podcasts"}
        if type_avgs[highest] - type_avgs[lowest] >= 0.2:
            taste_comparison = f"You rate {labels[highest]} higher than {labels[lowest]}."

    # Quiz status for taste card
    from app.services.taste_quiz_scoring import load_quiz_results
    quiz_results = load_quiz_results(db, user.id)
    quizzes_done = sum(1 for t in ("movies", "tv", "books") if quiz_results and quiz_results.get(t, {}).get("profiles"))

    # Taste DNA teaser — pull the top quiz profile name for an intriguing hook
    taste_teaser = ""
    if quiz_results and quizzes_done > 0:
        all_profiles: list[tuple[str, str, float]] = []
        category_labels = {"movies": "movie", "tv": "TV", "books": "book"}
        for cat, label in category_labels.items():
            profiles = (quiz_results.get(cat) or {}).get("profiles", [])
            for p in profiles[:1]:
                name = p.get("name", "")
                sim = p.get("similarity", 0)
                if name:
                    all_profiles.append((name, label, sim))
        if all_profiles:
            best = max(all_profiles, key=lambda x: x[2])
            pct = round(best[2] * 100)
            taste_teaser = f'Your {best[1]} taste: {pct}% "{best[0]}"'

    # Count of other NextUp users the current user could pair with in
    # Together mode. Drives the Home teaser copy — zero partners gets
    # a strong 'invite your people' hook, non-zero gets the standard
    # pairing sell with a secondary 'invite more' nudge.
    # --- Together social feed (batch query, no N+1) ------------------
    partners = db.query(User).filter(User.id != user.id).all()
    together_partner_count = len(partners)

    together_highlights: list[dict] = []
    if together_partner_count > 0:
        partner_ids = [p.id for p in partners]
        partner_map = {p.id: p for p in partners}

        # Get current user's titles in one query
        my_title_rows = (
            db.query(MediaEntry.title, MediaEntry.status)
            .filter(MediaEntry.user_id == user.id)
            .all()
        )
        my_titles = set(t.lower() for t, _ in my_title_rows)
        my_queue_titles = set(t.lower() for t, s in my_title_rows if s == "want_to_consume")

        # Batch load: all partner entries rated 4+ (one query for ALL partners)
        all_partner_rated = (
            db.query(MediaEntry)
            .filter(
                MediaEntry.user_id.in_(partner_ids),
                MediaEntry.rating.isnot(None),
                MediaEntry.rating >= 4,
            )
            .order_by(MediaEntry.rated_at.desc().nullslast(), MediaEntry.updated_at.desc())
            .all()
        )

        # Batch load: all partner queue items
        all_partner_queued = (
            db.query(MediaEntry)
            .filter(
                MediaEntry.user_id.in_(partner_ids),
                MediaEntry.status == "want_to_consume",
            )
            .order_by(MediaEntry.created_at.desc())
            .all()
        )

        raw_highlights: list[tuple[int, float, dict]] = []

        for entry in all_partner_rated:
            partner = partner_map.get(entry.user_id)
            if not partner:
                continue
            first_name = partner.name.split()[0] if partner.name else "Someone"
            title_lower = entry.title.lower()
            verb = {"movie": "watched", "tv": "watched", "book": "read", "podcast": "listened to"}.get(entry.media_type, "checked out")
            if title_lower in my_titles:
                priority = 0
                action = f"{first_name} rated {entry.title} {entry.rating}/5 — you've {verb} this too"
            elif title_lower in my_queue_titles:
                priority = 1
                action = f"{first_name} rated {entry.title} {entry.rating}/5 — it's in your queue"
            else:
                priority = 2
                action = f"{first_name} rated {entry.title} {entry.rating}/5"
            recency = (entry.rated_at or entry.updated_at).timestamp() if (entry.rated_at or entry.updated_at) else 0
            raw_highlights.append((priority, recency, {
                "action": action,
                "partner_name": first_name,
                "partner_picture": partner.picture or "",
                "title": entry.title,
                "media_type": entry.media_type,
                "rating": entry.rating,
                "has_overlap": priority < 2,
            }))

        for entry in all_partner_queued:
            title_lower = entry.title.lower()
            if title_lower in my_queue_titles:
                partner = partner_map.get(entry.user_id)
                if not partner:
                    continue
                first_name = partner.name.split()[0] if partner.name else "Someone"
                recency = entry.created_at.timestamp() if entry.created_at else 0
                raw_highlights.append((0, recency, {
                    "action": f"You and {first_name} both want to check out {entry.title}",
                    "partner_name": first_name,
                    "partner_picture": partner.picture or "",
                    "title": entry.title,
                    "media_type": entry.media_type,
                    "rating": None,
                    "has_overlap": True,
                }))

        # Sort by priority (overlap first), then most recent activity
        raw_highlights.sort(key=lambda x: (x[0], -x[1]))
        seen_titles: set[str] = set()
        seen_partners: set[str] = set()
        # First pass: one highlight per partner (overlap preferred, most recent wins)
        for _, _, h in raw_highlights:
            if h["partner_name"] in seen_partners:
                continue
            if h["title"].lower() in seen_titles:
                continue
            together_highlights.append(h)
            seen_titles.add(h["title"].lower())
            seen_partners.add(h["partner_name"])
            if len(together_highlights) >= 3:
                break
        # Second pass: if we don't have 3 yet, allow repeat partners
        if len(together_highlights) < 3:
            for _, _, h in raw_highlights:
                if h["title"].lower() in seen_titles:
                    continue
                together_highlights.append(h)
                seen_titles.add(h["title"].lower())
                if len(together_highlights) >= 3:
                    break

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "total": total,
            "is_new_user": rated_count < 5 and quizzes_done == 0,
            "currently": currently,
            "unrated_batch": unrated_batch,
            "unrated_total": unrated_total,
            "up_next": up_next,
            "best_bet_media_type": best_bet_media_type,
            "rated_count": rated_count,
            "queue_count": queue_count,
            "type_counts": type_counts,
            "quizzes_done": quizzes_done,
            "together_partner_count": together_partner_count,
            "together_highlights": together_highlights,
            "avg_rating": avg_rating,
            "taste_teaser": taste_teaser,
            "taste_comparison": taste_comparison,
            "rated_this_month": rated_this_month,
            "fives_count": fives_count,
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
    bottom. Also loads the user's onboarding picks (media mix +
    era + scenes) so the page can display them with an 'Edit' link
    back to /onboarding."""
    from app.services.taste_quiz_scoring import get_onboarding_display, load_onboarding, load_quiz_results

    quiz_results = load_quiz_results(db, user.id)
    quiz_status = {
        "movies": bool(quiz_results.get("movies", {}).get("profiles")) if quiz_results else False,
        "tv":     bool(quiz_results.get("tv", {}).get("profiles")) if quiz_results else False,
        "books":  bool(quiz_results.get("books", {}).get("profiles")) if quiz_results else False,
    }
    quiz_status["completed_count"] = sum(1 for v in (quiz_status["movies"], quiz_status["tv"], quiz_status["books"]) if v)
    quiz_status["total"] = 3

    onboarding_display = get_onboarding_display(load_onboarding(db, user.id))

    from app.services.signal_strength import calculate_signal
    from app.services.taste_quiz_scoring import load_streaming_services
    signal = calculate_signal(db, user.id)
    user_services = load_streaming_services(db, user.id)

    return templates.TemplateResponse(
        "taste_dna.html",
        {"request": request, "user": user, "quiz_status": quiz_status, "onboarding_display": onboarding_display, "signal": signal, "user_services": user_services},
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
    "wind_down":       "Suggest something to wind down with before bed — think easy sitcoms, cooking shows, cozy comfort TV, or a short calming book. Nothing demanding, nothing dark. Familiar, warm, and easy to put down when sleep comes. Match it tightly to what this person actually watches and reads.",
    "background_work": "Recommend something I can have on in the background while I work — familiar or conversational, doesn't demand my attention but rewards it when I lean in.",
    "weekend_binge": "Recommend something for a weekend stretch — the kind of thing that pulls you forward and makes time disappear. Could be a series, a book, a film, a podcast run — whatever fits this person's taste. The quality that matters is bingeability: you finish one part and immediately want the next. Not about length or format, about that feeling of being completely inside something.",
    "quick_escape":    "Recommend a quick escape — a fun movie or short-form TV, 15-90 minutes, something to get me out of my own head.",
}


@router.get("/discover")
async def discover_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    context: str | None = None,
):
    """Single 'find me something' surface."""
    # Redirect to onboarding if insufficient taste signal
    from app.services.taste_quiz_scoring import load_quiz_results as _lqr2
    _rated2 = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)
    ).count()
    _quiz2 = _lqr2(db, user.id)
    _has_quiz2 = any(
        (_quiz2 or {}).get(t, {}).get("profiles")
        for t in ("movies", "tv", "books")
    )
    if _rated2 < 5 and not _has_quiz2:
        return RedirectResponse("/onboarding", status_code=302)

    if context and context in _CONTEXT_TO_MOOD:
        from urllib.parse import urlencode

        target = "/discover?" + urlencode({"mood": _CONTEXT_TO_MOOD[context]})
        return RedirectResponse(url=target, status_code=303)

    from app.services.taste_quiz_scoring import load_streaming_services
    from app.services.tmdb import TIER1_PROVIDERS
    user_services = load_streaming_services(db, user.id)
    service_labels = {pid: name for pid, name in TIER1_PROVIDERS.items()}

    return templates.TemplateResponse("discover.html", {
        "request": request,
        "user": user,
        "user_services": user_services,
        "service_labels": service_labels,
    })


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
async def quick_start_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    # If user hasn't done onboarding (generation + scenes), send them there first
    return templates.TemplateResponse("quick_start.html", {"request": request, "user": user})


@router.get("/onboarding")
async def onboarding_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """4-step taste-profile onboarding wizard."""
    from app.services.taste_quiz_scoring import load_onboarding, load_quiz_results

    # If user already has a taste profile, send them home instead
    _rc = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)
    ).count()
    _qr = load_quiz_results(db, user.id)
    _hq = any((_qr or {}).get(t, {}).get("profiles") for t in ("movies", "tv", "books"))
    if (_rc >= 5 or _hq) and not request.query_params.get("preview"):
        return RedirectResponse("/")


    saved = load_onboarding(db, user.id) or {}

    # Check if user has unrated items — if so, onboarding should prompt
    # them to rate those first ("You said you watched these. How were they?")
    unrated_items = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "consumed",
            MediaEntry.rating.is_(None),
        )
        .order_by(MediaEntry.created_at.desc())
        .limit(8)
        .all()
    )

    return templates.TemplateResponse(
        "onboarding.html",
        {
            "request": request,
            "user": user,
            "saved_media_types": saved.get("media_types", []),
            "saved_generation": saved.get("generation", "mix"),
            "saved_scenes": saved.get("scenes", []),
            "saved_services": saved.get("streaming_services", []),
            "unrated_items": unrated_items,
            "rated_count": _rc,
        },
    )


@router.get("/quick-start/movies")
async def quick_start_movies_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
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
async def quick_start_tv_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
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
async def quick_start_books_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Legacy combined books quiz — fiction + nonfiction in one flow."""
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


@router.get("/quick-start/books/fiction")
async def quick_start_books_fiction_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Fiction-only books quiz."""
    return templates.TemplateResponse(
        "quick_start_quiz.html",
        {
            "request": request,
            "user": user,
            "quiz_slug": "books_fiction",
            "quiz_title": "Fiction taste quiz",
            "quiz_blurb": "20 novels, one at a time. We'll figure out how you read fiction — prose vs plot, ideas vs feelings, how dark you can go — and lock in your reader profile.",
            "item_label": "Book",
        },
    )


@router.get("/quick-start/books/nonfiction")
async def quick_start_books_nonfiction_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Nonfiction-only books quiz."""
    return templates.TemplateResponse(
        "quick_start_quiz.html",
        {
            "request": request,
            "user": user,
            "quiz_slug": "books_nonfiction",
            "quiz_title": "Nonfiction taste quiz",
            "quiz_blurb": "10 nonfiction titles spanning memoir, ideas, science, history, and true crime. We'll figure out whether you read for the story, the argument, or the voice.",
            "item_label": "Book",
        },
    )


@router.get("/media/{media_type}/{external_id}")
async def media_detail_page(request: Request, media_type: str, external_id: str, user: User = Depends(require_user)):
    return templates.TemplateResponse(
        "media_detail.html",
        {"request": request, "user": user, "media_type": media_type, "external_id": external_id},
    )
