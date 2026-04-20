import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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


def _genre_set(entry) -> set[str]:
    """Extract normalized genre set from an entry."""
    if not entry.genres:
        return set()
    return {g.strip().lower() for g in entry.genres.split(",") if g.strip()}


def _predict_fit(entry, partner_entries) -> float | None:
    """Simple genre-based heuristic: how well would this item fit the partner?"""
    item_genres = _genre_set(entry)
    if not item_genres:
        return None

    partner_rated = [e for e in partner_entries if e.rating and e.rating >= 1]
    if len(partner_rated) < 3:
        return None

    # Find partner items with overlapping genres
    genre_scores = []
    for pe in partner_rated:
        pe_genres = _genre_set(pe)
        if pe_genres & item_genres:
            genre_scores.append(pe.rating)

    if len(genre_scores) >= 3:
        return round(sum(genre_scores) / len(genre_scores), 1)
    elif genre_scores:
        # Blend with overall average
        overall_avg = sum(e.rating for e in partner_rated) / len(partner_rated)
        genre_avg = sum(genre_scores) / len(genre_scores)
        blended = (genre_avg * len(genre_scores) + overall_avg * 2) / (len(genre_scores) + 2)
        return round(blended, 1)
    else:
        # No genre overlap — use overall average with penalty
        overall_avg = sum(e.rating for e in partner_rated) / len(partner_rated)
        return round(max(overall_avg - 0.5, 1.0), 1)


def _serialize_entry(entry, predicted_for_partner=None, label=None) -> dict:
    return {
        "title": entry.title,
        "media_type": entry.media_type,
        "year": entry.year,
        "image_url": entry.image_url,
        "external_id": entry.external_id or "",
        "source": entry.source or "",
        "description": entry.description or "",
        "their_rating": entry.rating,
        "predicted_for_partner": predicted_for_partner,
        "label": label,
    }


@router.get("/compare")
async def compare(
    other_user_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Compare taste profiles and generate recommendations using a
    data-first approach: surface items from each user's library that
    the other would enjoy, plus queue crossovers and rewatch candidates.
    AI fills in a small number of fresh discoveries."""
    from app.config import settings
    from app.routers.media import _smart_search, _build_genre_breakdown
    from app.services.taste_quiz_scoring import load_streaming_services, load_onboarding
    from app.services.tmdb import TIER1_PROVIDERS

    other = db.query(User).filter(User.id == other_user_id).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")

    my_entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    their_entries = db.query(MediaEntry).filter(MediaEntry.user_id == other.id).all()

    my_name = user.name or "You"
    them_name = other.name or "Them"

    # Index by title for quick lookup
    my_titles = {e.title.lower(): e for e in my_entries}
    their_titles = {e.title.lower(): e for e in their_entries}

    # Dismissed items
    now = datetime.utcnow()
    dismissed = set()
    for d in db.query(DismissedItem).filter(DismissedItem.user_id.in_([user.id, other.id])).all():
        if d.snoozed_until and d.snoozed_until < now:
            continue
        dismissed.add(d.title.lower())

    # Streaming services
    my_services = set(load_streaming_services(db, user.id) or [])
    their_services = set(load_streaming_services(db, other.id) or [])

    # ================================================================
    # 1. SHARED LOVED — items both rated 4+ (rewatch together)
    # ================================================================
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

    # Shared genres
    my_genres: dict[str, int] = {}
    their_genres: dict[str, int] = {}
    for e in my_entries:
        for g in _genre_set(e):
            my_genres[g] = my_genres.get(g, 0) + 1
    for e in their_entries:
        for g in _genre_set(e):
            their_genres[g] = their_genres.get(g, 0) + 1
    shared_genre_names = sorted(
        [g for g in my_genres if g in their_genres],
        key=lambda g: my_genres[g] + their_genres[g], reverse=True,
    )[:8]

    # ================================================================
    # 2. "THEY LOVED, YOU HAVEN'T SEEN" — data-driven, no AI
    # ================================================================
    they_loved_you_havent = []
    for e in their_entries:
        if not e.rating or e.rating < 4:
            continue
        if e.title.lower() in my_titles:
            continue  # I already have it
        if e.title.lower() in dismissed:
            continue
        predicted = _predict_fit(e, my_entries)
        if predicted and predicted >= 3.0:
            they_loved_you_havent.append({
                **_serialize_entry(e, predicted_for_partner=predicted),
                "source_user": them_name,
                "predicted_rating_me": predicted,
                "predicted_rating_them": e.rating,
            })
    they_loved_you_havent.sort(key=lambda x: x["predicted_rating_me"], reverse=True)

    # ================================================================
    # 3. "YOU LOVED, THEY HAVEN'T SEEN"
    # ================================================================
    you_loved_they_havent = []
    for e in my_entries:
        if not e.rating or e.rating < 4:
            continue
        if e.title.lower() in their_titles:
            continue
        if e.title.lower() in dismissed:
            continue
        predicted = _predict_fit(e, their_entries)
        if predicted and predicted >= 3.0:
            you_loved_they_havent.append({
                **_serialize_entry(e, predicted_for_partner=predicted),
                "source_user": my_name,
                "predicted_rating_me": e.rating,
                "predicted_rating_them": predicted,
            })
    you_loved_they_havent.sort(key=lambda x: x["predicted_rating_them"], reverse=True)

    # ================================================================
    # 4. QUEUE CROSSOVERS — in one person's queue AND liked by the other
    # ================================================================
    queue_picks = []
    my_queue = [e for e in my_entries if e.status == "want_to_consume"]
    their_queue = [e for e in their_entries if e.status == "want_to_consume"]

    for e in my_queue:
        if e.title.lower() in dismissed:
            continue
        # Is this in the other's library and rated well?
        their_match = their_titles.get(e.title.lower())
        if their_match and their_match.rating and their_match.rating >= 4:
            queue_picks.append({
                **_serialize_entry(e),
                "source_user": my_name,
                "queue_owner": my_name,
                "predicted_rating_me": None,
                "predicted_rating_them": their_match.rating,
                "label": f"In {my_name.split()[0]}'s queue — {them_name.split()[0]} rated it {their_match.rating}/5",
            })
        elif not their_match:
            # Not in their library — predict fit
            predicted = _predict_fit(e, their_entries)
            if predicted and predicted >= 3.5:
                queue_picks.append({
                    **_serialize_entry(e),
                    "source_user": my_name,
                    "queue_owner": my_name,
                    "predicted_rating_me": None,
                    "predicted_rating_them": predicted,
                    "label": f"In {my_name.split()[0]}'s queue",
                })

    for e in their_queue:
        if e.title.lower() in dismissed:
            continue
        my_match = my_titles.get(e.title.lower())
        if my_match and my_match.rating and my_match.rating >= 4:
            queue_picks.append({
                **_serialize_entry(e),
                "source_user": them_name,
                "queue_owner": them_name,
                "predicted_rating_me": my_match.rating,
                "predicted_rating_them": None,
                "label": f"In {them_name.split()[0]}'s queue — {my_name.split()[0]} rated it {my_match.rating}/5",
            })
        elif not my_match:
            predicted = _predict_fit(e, my_entries)
            if predicted and predicted >= 3.5:
                queue_picks.append({
                    **_serialize_entry(e),
                    "source_user": them_name,
                    "queue_owner": them_name,
                    "predicted_rating_me": predicted,
                    "predicted_rating_them": None,
                    "label": f"In {them_name.split()[0]}'s queue",
                })

    # Deduplicate queue_picks
    seen_queue = set()
    deduped_queue = []
    for qp in queue_picks:
        k = qp["title"].lower()
        if k not in seen_queue:
            seen_queue.add(k)
            deduped_queue.append(qp)
    queue_picks = deduped_queue

    # ================================================================
    # 5. MERGE DATA-DRIVEN WATCH PICKS — interleave for balance
    # ================================================================
    # Take up to 4 from each "loved" pool, interleaved
    watch_from_data = []
    seen_watch = set()
    max_each = 5
    for i in range(max_each):
        if i < len(they_loved_you_havent):
            t = they_loved_you_havent[i]
            if t["title"].lower() not in seen_watch and t["media_type"] in ("movie", "tv"):
                watch_from_data.append(t)
                seen_watch.add(t["title"].lower())
        if i < len(you_loved_they_havent):
            t = you_loved_they_havent[i]
            if t["title"].lower() not in seen_watch and t["media_type"] in ("movie", "tv"):
                watch_from_data.append(t)
                seen_watch.add(t["title"].lower())

    # Add queue picks (movies/TV only)
    for qp in queue_picks:
        if qp["title"].lower() not in seen_watch and qp["media_type"] in ("movie", "tv"):
            watch_from_data.append(qp)
            seen_watch.add(qp["title"].lower())
            if len(watch_from_data) >= 10:
                break

    # ================================================================
    # 6. AI FRESH DISCOVERIES — small focused call
    # ================================================================
    ai_watch = []
    ai_read = []
    ai_listen = []

    if settings.gemini_api_key:
        from app.services.gemini import generate

        # Genre exclusions
        _onb_me = load_onboarding(db, user.id)
        _onb_them = load_onboarding(db, other.id)
        _scenes_me = set((_onb_me or {}).get("scenes", []))
        _scenes_them = set((_onb_them or {}).get("scenes", []))
        _deal = {"anime": "anime, manga, or Japanese animation", "k_content": "K-drama or Korean content"}
        _excl = []
        for key, label in _deal.items():
            if key not in _scenes_me and key not in _scenes_them:
                gs = "anime" if key == "anime" else "k-drama"
                has = any(e.genres and gs in e.genres.lower() and (e.rating or 0) >= 3
                          for entries in [my_entries, their_entries] for e in entries)
                if not has:
                    _excl.append(label)
        genre_excl = f"\nHARD EXCLUSIONS: {', '.join(_excl)}.\n" if _excl else ""

        # Streaming context
        streaming_ctx = ""
        if my_services or their_services:
            my_svc = ", ".join(TIER1_PROVIDERS.get(p, str(p)) for p in my_services) if my_services else "unknown"
            their_svc = ", ".join(TIER1_PROVIDERS.get(p, str(p)) for p in their_services) if their_services else "unknown"
            streaming_ctx = f"\nSTREAMING: {my_name} has: {my_svc}. {them_name} has: {their_svc}. TV shows MUST be on a service at least one has.\n"

        # Compact taste summaries — just top 6 per type
        def compact_summary(entries, name):
            by_type = {}
            for e in entries:
                if e.rating and e.rating >= 4:
                    by_type.setdefault(e.media_type, []).append(e)
            for mt in by_type:
                by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)
            lines = [f"{name}'s favorites:"]
            for mt in ("movie", "tv", "book", "podcast"):
                items = by_type.get(mt, [])[:6]
                if items:
                    lines.append(", ".join(f"{e.title} ({e.rating}/5)" for e in items))
            return " ".join(lines)

        my_compact = compact_summary(my_entries, my_name.split()[0])
        their_compact = compact_summary(their_entries, them_name.split()[0])

        # Genre breakdowns
        my_gb = _build_genre_breakdown(my_entries)
        their_gb = _build_genre_breakdown(their_entries)

        # Avoid list — everything either has consumed/queued + data-driven picks already surfaced
        # All titles from both users — the AI must not recommend anything either has
        avoid_titles = seen_watch | {e.title.lower() for e in my_entries} | {e.title.lower() for e in their_entries}
        # Send as many as we can fit — prioritize highly-rated (AI is most tempted by those)
        highly_rated = sorted(
            [e.title for e in my_entries + their_entries if e.rating and e.rating >= 4],
            key=lambda t: t.lower()
        )
        other_titles = sorted(avoid_titles - {t.lower() for t in highly_rated})
        ordered_avoid = highly_rated + other_titles
        char_budget = 8000
        avoid_list = []
        for t in ordered_avoid:
            if char_budget <= 0:
                break
            avoid_list.append(t)
            char_budget -= len(t) + 2
        avoid_str = "\n".join(f"- {t}" for t in avoid_list)

        # Release the DB connection before AI call
        db.close()

        try:
            prompt = f"""Recommend items for two people to enjoy together. Focus on the OVERLAP in their taste.
{streaming_ctx}{genre_excl}
{my_compact}
{my_gb if my_gb else ''}

{their_compact}
{their_gb if their_gb else ''}

Find 4 movies/TV shows, 2 books, and 2 podcasts that BOTH would rate 3.5+. Treat the smaller profile as the primary filter.

Do NOT recommend: {avoid_str}

FOCUS: Pick genuine overlap items. Predict ratings honestly. No descriptions needed.

Return ONLY valid JSON:
{{
  "watch": [{{"title": "...", "creator": "...", "media_type": "movie|tv", "year": 2020, "predicted_rating_me": 4.0, "predicted_rating_them": 3.5}}],
  "read": [{{"title": "...", "creator": "...", "media_type": "book", "year": 2020, "predicted_rating_me": 4.0, "predicted_rating_them": 3.5}}],
  "listen": [{{"title": "...", "creator": "...", "media_type": "podcast", "year": 2020, "predicted_rating_me": 4.0, "predicted_rating_them": 3.5}}]
}}"""

            text = (await generate(prompt, temperature=0)).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            first = text.find("{")
            last = text.rfind("}")
            if first >= 0 and last > first:
                text = text[first:last + 1]
            parsed = json.loads(text)

            # Enrich AI picks
            import asyncio

            async def enrich(item):
                if not item:
                    return None
                try:
                    title = item.get("title", "")
                    creator = item.get("creator", "")
                    mt = item.get("media_type")
                    matches = await _smart_search(title, mt, creator)
                    if matches:
                        best = matches[0]
                        return {
                            "title": best.title, "media_type": best.media_type,
                            "year": best.year, "image_url": best.image_url,
                            "external_id": best.external_id, "source": best.source,
                            "description": best.description or "",
                            "predicted_rating_me": item.get("predicted_rating_me"),
                            "predicted_rating_them": item.get("predicted_rating_them"),
                        }
                except Exception:
                    pass
                return {
                    "title": item.get("title", ""), "media_type": item.get("media_type", "movie"),
                    "year": item.get("year"), "image_url": None,
                    "external_id": "", "source": "", "description": "",
                    "predicted_rating_me": item.get("predicted_rating_me"),
                    "predicted_rating_them": item.get("predicted_rating_them"),
                }

            watch_raw = parsed.get("watch", [])[:5]
            read_raw = parsed.get("read", [])[:3]
            listen_raw = parsed.get("listen", [])[:3]
            all_raw = watch_raw + read_raw + listen_raw
            all_enriched = await asyncio.gather(*[enrich(it) for it in all_raw])

            # Post-filter: drop any AI pick that's in either user's library
            def _not_avoided(item):
                if not item:
                    return False
                return item.get("title", "").lower() not in avoid_titles

            w_end = len(watch_raw)
            r_end = w_end + len(read_raw)
            ai_watch = [c for c in all_enriched[:w_end] if _not_avoided(c)]
            ai_read = [c for c in all_enriched[w_end:r_end] if _not_avoided(c)]
            ai_listen = [c for c in all_enriched[r_end:] if _not_avoided(c)]

        except Exception as e:
            log.error("together AI failed: %s", str(e), exc_info=True)

    return {
        "other_user": {"id": other.id, "name": other.name, "picture": other.picture},
        "my_name": my_name,
        "shared_loved": shared_loved[:12],
        "shared_genres": shared_genre_names,
        "watch_from_data": watch_from_data[:8],
        "watch_from_ai": ai_watch,
        "read_together": ai_read,
        "listen_together": ai_listen,
        "queue_picks": queue_picks[:6],
    }
