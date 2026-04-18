import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import DismissedItem, MediaEntry, User

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/users")
def list_users(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """List all users except the current one, for picking a comparison partner."""
    users = db.query(User).filter(User.id != user.id).all()
    return [
        {"id": u.id, "name": u.name, "picture": u.picture}
        for u in users
    ]


@router.get("/compare")
async def compare(
    other_user_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Compare your profile with another user's profile to find shared interests."""
    from app.config import settings
    from app.services.gemini import generate
    from app.services.unified_search import unified_search

    other = db.query(User).filter(User.id == other_user_id).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")

    my_entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    their_entries = db.query(MediaEntry).filter(MediaEntry.user_id == other.id).all()

    # Items both rated ≥7
    my_rated = {e.title.lower(): e for e in my_entries if e.rating is not None}
    their_rated = {e.title.lower(): e for e in their_entries if e.rating is not None}

    shared_loved = []
    for title_lower, my_e in my_rated.items():
        if title_lower in their_rated:
            their_e = their_rated[title_lower]
            if (my_e.rating or 0) >= 4 and (their_e.rating or 0) >= 4:
                shared_loved.append({
                    "title": my_e.title,
                    "media_type": my_e.media_type,
                    "year": my_e.year,
                    "image_url": my_e.image_url,
                    "external_id": my_e.external_id,
                    "source": my_e.source,
                    "my_rating": my_e.rating,
                    "their_rating": their_e.rating,
                    "combined": (my_e.rating + their_e.rating) / 2,
                })
    shared_loved.sort(key=lambda x: x["combined"], reverse=True)

    # Shared genres from both profiles
    my_genres: dict[str, int] = {}
    their_genres: dict[str, int] = {}
    for e in my_entries:
        if e.genres:
            for g in e.genres.split(","):
                g = g.strip()
                if g:
                    my_genres[g] = my_genres.get(g, 0) + 1
    for e in their_entries:
        if e.genres:
            for g in e.genres.split(","):
                g = g.strip()
                if g:
                    their_genres[g] = their_genres.get(g, 0) + 1
    shared_genres = sorted(
        [g for g in my_genres if g in their_genres],
        key=lambda g: my_genres[g] + their_genres[g],
        reverse=True,
    )[:8]

    if not settings.gemini_api_key:
        return {
            "other_user": {"id": other.id, "name": other.name, "picture": other.picture},
            "shared_loved": shared_loved[:10],
            "shared_genres": shared_genres,
            "watch_together": None,
            "candidates": [],
        }

    # Build taste summaries for both users (grouped by type, top-rated)
    def build_summary(entries, name):
        by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
        for e in entries:
            if e.rating and e.rating >= 4:
                by_type.setdefault(e.media_type, []).append(e)
        for mt in by_type:
            by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

        label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
        lines = [f"=== {name}'s profile ==="]
        for mt, label in label_map.items():
            items = by_type.get(mt, [])[:8]
            if items:
                type_lines = [f"  - {e.title} — {e.rating}/5" for e in items]
                lines.append(f"{label}:\n" + "\n".join(type_lines))
        return "\n\n".join(lines)

    my_summary = build_summary(my_entries, user.name)
    their_summary = build_summary(their_entries, other.name)

    avoid = set()
    for e in my_entries:
        avoid.add(e.title.lower())
    for e in their_entries:
        avoid.add(e.title.lower())
    # Also include dismissed items from both users
    for d in db.query(DismissedItem.title).filter(DismissedItem.user_id.in_([user.id, other.id])).all():
        avoid.add(d.title.lower())
    # Send ALL avoided titles — truncating caused dismissed items to slip through
    avoid_str = "\n".join(f"- {t}" for t in sorted(avoid)) if avoid else "none"

    from app.services.taste_quiz_scoring import load_streaming_services
    from app.services.tmdb import TIER1_PROVIDERS

    my_services = load_streaming_services(db, user.id)
    their_services = load_streaming_services(db, other.id)
    if my_services or their_services:
        my_svc_names = ", ".join(TIER1_PROVIDERS.get(pid, f"Service {pid}") for pid in my_services) if my_services else "unknown"
        their_svc_names = ", ".join(TIER1_PROVIDERS.get(pid, f"Service {pid}") for pid in their_services) if their_services else "unknown"
        together_streaming_ctx = f"\nSTREAMING: {user.name} subscribes to: {my_svc_names}. {other.name} subscribes to: {their_svc_names}. Strongly prefer items both can access on their shared services.\n"
    else:
        together_streaming_ctx = ""

    try:
        prompt = f"""You are a cross-medium taste expert. Find things that BOTH of these people would love — based on their individual profiles.

{my_summary}

{their_summary}
{together_streaming_ctx}
TASK: Recommend 5 cross-medium items (a mix of movies, TV, books, podcasts) that BOTH people would rate ≥4. For each, predict how each person would rate it on a 1-5 scale.

CRITICAL:
- NEVER recommend anything on this list — these are titles both users already have or have explicitly rejected:
{avoid_str}
- Do NOT recommend niche anime, fan-service shows, or obscure titles unless BOTH profiles show strong anime/manga interest
- The reason should cite specific items from BOTH profiles
- One of the 5 should be marked as "watch_together_pick": true — the BEST single thing to consume together

Return ONLY valid JSON, no markdown:
{{
  "watch_together_pick": {{"title": "...", "media_type": "movie|tv|book|podcast", "year": 2020, "predicted_rating_me": 4.5, "predicted_rating_them": 4.0, "reason": "cross-medium reason citing both profiles"}},
  "candidates": [
    {{"title": "...", "media_type": "...", "year": 2020, "predicted_rating_me": 4.0, "predicted_rating_them": 3.5, "reason": "..."}},
    ... 4 more items
  ]
}}"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
    except Exception as e:
        log.error("compare AI failed: %s", str(e))
        parsed = {"watch_together_pick": None, "candidates": []}

    # Enrich with posters
    import asyncio

    async def enrich(item):
        if not item:
            return None
        try:
            matches = await unified_search(item.get("title", ""), item.get("media_type"))
            if matches:
                best = matches[0]
                return {
                    "title": best.title,
                    "media_type": best.media_type,
                    "year": best.year,
                    "image_url": best.image_url,
                    "external_id": best.external_id,
                    "source": best.source,
                    "predicted_rating_me": item.get("predicted_rating_me"),
                    "predicted_rating_them": item.get("predicted_rating_them"),
                    "reason": item.get("reason", ""),
                }
        except Exception:
            pass
        return {
            "title": item.get("title", ""),
            "media_type": item.get("media_type", "movie"),
            "year": item.get("year"),
            "image_url": None,
            "external_id": "",
            "source": "",
            "predicted_rating_me": item.get("predicted_rating_me"),
            "predicted_rating_them": item.get("predicted_rating_them"),
            "reason": item.get("reason", ""),
        }

    # Parallel enrichment: watch_together + all candidates at once
    watch_together_raw = parsed.get("watch_together_pick")
    candidates_raw = parsed.get("candidates", [])[:5]
    all_to_enrich = [watch_together_raw] + candidates_raw if watch_together_raw else candidates_raw
    all_enriched = await asyncio.gather(*[enrich(item) for item in all_to_enrich])

    if watch_together_raw:
        watch_together = all_enriched[0]
        candidates = [c for c in all_enriched[1:] if c is not None]
    else:
        watch_together = None
        candidates = [c for c in all_enriched if c is not None]

    # Post-filter: drop any title the AI recommended despite being in the avoid set
    def _is_avoided(title):
        return title and title.lower() in avoid
    if watch_together and _is_avoided(watch_together.get("title")):
        watch_together = None
    candidates = [c for c in candidates if not _is_avoided(c.get("title"))]

    # Sort by the lower of the two predicted ratings (higher = safer for both)
    candidates.sort(key=lambda x: min(x.get("predicted_rating_me") or 0, x.get("predicted_rating_them") or 0), reverse=True)

    return {
        "other_user": {"id": other.id, "name": other.name, "picture": other.picture},
        "my_name": user.name,
        "shared_loved": shared_loved[:10],
        "shared_genres": shared_genres,
        "watch_together": watch_together,
        "candidates": candidates,
    }
