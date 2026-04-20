"""Tonight welcome — AI-generated context-aware greeting + recommendation.

One Gemini call per action cycle. Cached until the user adds, rates,
starts, or finishes something. No timer-based expiry.
"""

import json
import logging

from sqlalchemy.orm import Session

from app import cache
from app.models import MediaEntry, User

log = logging.getLogger(__name__)

CACHE_PREFIX = "tonight_welcome"


def _cache_key(user_id: int) -> str:
    return f"{CACHE_PREFIX}:{user_id}"


async def build_tonight(user: User, db: Session) -> dict | None:
    """Build the tonight welcome block.

    Returns a dict with:
        welcome_text: str  — 2-3 sentence AI observation about recent activity
        rec_title: str     — recommended title
        rec_creator: str   — author/director
        rec_media_type: str
        rec_year: int | None
        rec_reason: str    — why this fits the thread (1 sentence)

    Returns None if the user has no recent activity to riff on.
    """
    # Check cache first — survives until next profile change
    cached = cache.get(_cache_key(user.id))
    if cached is not None:
        return cached

    # Gather recent activity
    recent = _gather_recent_activity(user, db)

    # One Gemini call — different prompt depending on user state
    if recent["has_activity"]:
        result = await _generate_welcome(user, recent)
    elif recent["top_rated"]:
        result = await _generate_welcome_new_user(user, recent)
    else:
        return None
    if not result:
        return None

    # Cache with very long TTL — busted by mark_profile_changed()
    # which clears tonight_welcome prefix
    cache.set(_cache_key(user.id), result, ttl_seconds=86400 * 30)
    return result


def _gather_recent_activity(user: User, db: Session) -> dict:
    """Pull the user's recent consuming, recently added, recently finished."""

    # Currently consuming
    consuming = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "consuming",
        )
        .order_by(MediaEntry.updated_at.desc())
        .limit(5)
        .all()
    )

    # Recently added to queue (last 2 weeks)
    from datetime import datetime, timedelta
    two_weeks_ago = datetime.utcnow() - timedelta(days=14)
    recently_queued = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "want_to_consume",
            MediaEntry.created_at >= two_weeks_ago,
        )
        .order_by(MediaEntry.created_at.desc())
        .limit(5)
        .all()
    )

    # Recently finished + rated
    recently_finished = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "consumed",
            MediaEntry.rated_at >= two_weeks_ago,
            MediaEntry.rating.isnot(None),
        )
        .order_by(MediaEntry.rated_at.desc())
        .limit(5)
        .all()
    )

    # All consumed titles for dedup
    all_titles = set()
    all_rows = db.query(MediaEntry.title).filter(
        MediaEntry.user_id == user.id
    ).all()
    for (t,) in all_rows:
        if t:
            all_titles.add(t.lower())

    has_activity = bool(consuming or recently_queued or recently_finished)

    # Top rated all time — used for new users or those without recent activity
    top_rated = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "consumed",
            MediaEntry.rating.isnot(None),
            MediaEntry.rating >= 4,
        )
        .order_by(MediaEntry.rating.desc(), MediaEntry.rated_at.desc())
        .limit(10)
        .all()
    )

    return {
        "has_activity": has_activity,
        "consuming": consuming,
        "recently_queued": recently_queued,
        "recently_finished": recently_finished,
        "top_rated": top_rated,
        "all_titles": all_titles,
    }


def _format_entry(e: MediaEntry) -> str:
    """Format a media entry for the prompt."""
    parts = [f'"{e.title}"']
    if e.creator:
        parts.append(f"by {e.creator}")
    parts.append(f"({e.media_type})")
    if e.rating:
        parts.append(f"rated {e.rating}/5")
    if e.genres:
        parts.append(f"[{e.genres}]")
    return " ".join(parts)


async def _generate_welcome(user: User, recent: dict) -> dict | None:
    """Single Gemini call to produce the welcome + recommendation."""
    from app.services.gemini import generate

    first_name = (user.name or "friend").split()[0]

    # Build activity context
    sections = []
    if recent["consuming"]:
        items = "\n".join(f"  - {_format_entry(e)}" for e in recent["consuming"])
        sections.append(f"Currently reading/watching/listening to:\n{items}")
    if recent["recently_finished"]:
        items = "\n".join(f"  - {_format_entry(e)}" for e in recent["recently_finished"])
        sections.append(f"Recently finished:\n{items}")
    if recent["recently_queued"]:
        items = "\n".join(f"  - {_format_entry(e)}" for e in recent["recently_queued"])
        sections.append(f"Recently added to queue:\n{items}")

    activity_block = "\n\n".join(sections)

    # Build the known-titles exclusion
    known_sample = list(recent["all_titles"])[:100]
    known_str = ", ".join(known_sample) if known_sample else "(none)"

    prompt = f"""You are the voice of NextUp, a media recommendation app. You're writing a short welcome for {first_name}'s home screen.

THEIR RECENT ACTIVITY:
{activity_block}

TASK:
Write ONE sentence starting with "Lately" about what connects their recent picks. Name 2 titles max. Keep it casual — like a friend texting, not a book report. Do NOT recommend anything.

RULES:
- Start with "Lately"
- One sentence only. Short.
- Warm, casual tone. Like you're catching up over coffee.
- Name 1-2 specific titles from their activity.
- Wrap every title in <em> tags (e.g. <em>Talking to Strangers</em>). All media titles get italics.
- No recommendations. No suggestions. Just an observation.

Return ONLY valid JSON:
{{
  "welcome_text": "Your sentence here with <em>Title</em> tags."
}}"""

    text = await generate(prompt, temperature=0.7)
    if not text:
        return None

    # Parse JSON
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last <= first:
        log.warning("tonight: could not find JSON in response: %s", text[:200])
        return None

    try:
        result = json.loads(text[first:last + 1])
    except json.JSONDecodeError:
        log.warning("tonight: JSON parse failed: %s", text[:200])
        return None

    if not result.get("welcome_text"):
        log.warning("tonight: missing welcome_text: %s", result)
        return None

    return result


async def _generate_welcome_new_user(user: User, recent: dict) -> dict | None:
    """Welcome for new users or those without recent activity — based on top 10."""
    from app.services.gemini import generate

    first_name = (user.name or "friend").split()[0]
    items = "\n".join(f"  - {_format_entry(e)}" for e in recent["top_rated"])

    prompt = f"""You are the voice of NextUp, a media recommendation app. You're writing a short welcome for {first_name}'s home screen. They're still building their profile so we're working with their all-time favorites.

THEIR TOP RATED:
{items}

TASK:
Write ONE sentence starting with "Lately" about the thread running through their favorites. Name 2 titles max. Casual tone — like a friend who gets their taste. Do NOT recommend anything.

RULES:
- Start with "Lately"
- One sentence only. Short.
- Warm, casual. Like texting a friend who pays attention.
- Name 1-2 specific titles.
- Wrap every title in <em> tags (e.g. <em>The Great Gatsby</em>). All media titles get italics.
- No recommendations. No suggestions. Just an observation.

Return ONLY valid JSON:
{{
  "welcome_text": "Your sentence here with <em>Title</em> tags."
}}"""

    text = await generate(prompt, temperature=0.7)
    if not text:
        return None

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    first = text.find("{")
    last = text.rfind("}")
    if first < 0 or last <= first:
        return None

    try:
        result = json.loads(text[first:last + 1])
    except json.JSONDecodeError:
        return None

    if not result.get("welcome_text"):
        return None

    return result
