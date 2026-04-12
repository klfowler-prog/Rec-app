import logging

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user

log = logging.getLogger(__name__)
from app.database import get_db
from app.models import User
from app.schemas import MediaResult

router = APIRouter()


@router.get("/search", response_model=list[MediaResult])
async def search_media(q: str = Query(..., min_length=1), media_type: str | None = None):
    """Search across all media APIs."""
    from app.services.unified_search import unified_search

    return await unified_search(q, media_type)


class BulkSearchItem(BaseModel):
    title: str
    media_type: str


class BulkSearchRequest(BaseModel):
    items: list[BulkSearchItem]


@router.post("/bulk-search")
async def bulk_search(req: BulkSearchRequest):
    """Search for multiple titles with explicit media types — in parallel."""
    import asyncio

    from app.services.unified_search import unified_search

    items = [(item.title.strip(), item.media_type) for item in req.items if item.title.strip()]
    if not items:
        return {}

    async def search_one(title, media_type):
        matches = await unified_search(title, media_type)
        matches = _rank_by_title_match(title, matches)
        return title, matches[:3] if matches else []

    found = await asyncio.gather(*[search_one(t, mt) for t, mt in items])
    return {title: matches for title, matches in found}


def _rank_by_title_match(query: str, results: list[MediaResult]) -> list[MediaResult]:
    """Rank search results by how closely the title matches the query."""
    query_lower = query.lower().strip()

    def score(item: MediaResult) -> float:
        title_lower = item.title.lower().strip()
        if title_lower == query_lower:
            return 100  # Exact match
        if title_lower.startswith(query_lower) or query_lower.startswith(title_lower):
            return 80  # Starts with
        if query_lower in title_lower or title_lower in query_lower:
            return 60  # Contains
        # Word overlap
        query_words = set(query_lower.split())
        title_words = set(title_lower.split())
        overlap = len(query_words & title_words)
        return (overlap / max(len(query_words), 1)) * 40

    return sorted(results, key=score, reverse=True)


@router.get("/trending/{media_type}")
async def get_trending(media_type: str = "all", limit: int = 10):
    """Get trending movies/TV from TMDB."""
    from app.services.tmdb import get_trending

    return await get_trending(media_type, "week", limit)


@router.get("/quiz-items")
async def quiz_items():
    """Get a curated mix of well-known items across genres for the taste quiz."""
    import asyncio

    from app import cache
    from app.services.tmdb import search as tmdb_search
    from app.services.open_library import search as search_books
    from app.services.itunes import search as search_podcasts

    cached = cache.get("quiz_items")
    if cached is not None:
        return cached

    # Curated movies spanning genres and decades
    movie_titles = [
        "The Shawshank Redemption", "Pulp Fiction", "The Dark Knight", "Inception",
        "Forrest Gump", "The Matrix", "Goodfellas", "Interstellar",
        "Parasite", "Get Out", "The Grand Budapest Hotel", "Mad Max Fury Road",
        "Eternal Sunshine of the Spotless Mind", "No Country for Old Men",
        "The Social Network", "Knives Out", "Everything Everywhere All at Once",
        "Arrival", "Whiplash", "The Departed", "Superbad", "Mean Girls",
        "The Notebook", "Bridesmaids", "Gladiator",
    ]
    # Curated TV shows spanning genres
    tv_titles = [
        "Breaking Bad", "The Office", "Game of Thrones", "Stranger Things",
        "The Wire", "Friends", "The Sopranos", "Fleabag",
        "Ted Lasso", "Succession", "Schitt's Creek", "The Crown",
        "Black Mirror", "The Mandalorian", "Severance", "The Bear",
        "Lost", "Mad Men", "Parks and Recreation", "The Last of Us",
        "Yellowstone", "Downton Abbey", "Ozark", "The Great British Bake Off",
    ]
    # Books spanning genres — literary fiction, sci-fi, thriller, nonfiction, YA
    book_titles = [
        "The Great Gatsby", "To Kill a Mockingbird", "1984", "Harry Potter",
        "The Hunger Games", "Gone Girl", "Dune", "The Alchemist",
        "Atomic Habits", "Educated", "Where the Crawdads Sing", "Project Hail Mary",
        "The Kite Runner", "Sapiens", "The Girl on the Train", "Normal People",
        "Becoming", "The Martian", "Circe", "A Court of Thorns and Roses",
        "The Silent Patient", "Outlander", "The Goldfinch", "Station Eleven",
    ]
    # Podcasts spanning genres
    podcast_titles = [
        "Serial", "The Daily", "Radiolab", "How I Built This",
        "Crime Junkie", "Freakonomics", "Conan O'Brien Needs a Friend", "SmartLess",
        "This American Life", "Stuff You Should Know", "The Joe Rogan Experience",
        "Armchair Expert", "Hidden Brain", "My Favorite Murder",
    ]

    async def search_tmdb_titles(titles, media_type):
        results = []
        searches = await asyncio.gather(
            *[tmdb_search(t, media_type) for t in titles], return_exceptions=True
        )
        for title, s in zip(titles, searches):
            if isinstance(s, list) and s:
                # Pick the best match by title similarity
                best = s[0]
                for item in s[:3]:
                    if item.title.lower() == title.lower():
                        best = item
                        break
                results.append(best)
        return results

    async def search_book_titles():
        results = []
        searches = await asyncio.gather(*[search_books(t) for t in book_titles], return_exceptions=True)
        for s in searches:
            if isinstance(s, list) and s:
                results.append(s[0])
        return results

    async def search_podcast_titles():
        results = []
        searches = await asyncio.gather(*[search_podcasts(t) for t in podcast_titles], return_exceptions=True)
        for s in searches:
            if isinstance(s, list) and s:
                results.append(s[0])
        return results

    movies, tv, books, podcasts = await asyncio.gather(
        search_tmdb_titles(movie_titles, "movie"),
        search_tmdb_titles(tv_titles, "tv"),
        search_book_titles(),
        search_podcast_titles(),
    )

    result = {
        "movie": [m.model_dump() for m in movies[:10]],
        "tv": [t.model_dump() for t in tv[:10]],
        "book": [b.model_dump() for b in books[:10]],
        "podcast": [p.model_dump() for p in podcasts[:8]],
    }
    cache.set("quiz_items", result, ttl_seconds=86400)  # 24 hours
    return result


@router.post("/refresh-recommendations")
async def refresh_recommendations():
    """Explicitly clear recommendation caches so they regenerate on next load."""
    from app import cache

    cache.force_refresh()
    return {"ok": True}


@router.get("/insights")
async def insights(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """AI-discovered cross-medium patterns and insights about the user's taste."""
    import json
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import MediaEntry

    cache_key = f"insights:{user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.gemini_api_key:
        return {"insights": []}

    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)).all()
    if len(entries) < 5:
        return {"insights": []}

    # Build grouped summary
    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    for e in entries:
        if e.rating and e.rating >= 6:
            by_type.setdefault(e.media_type, []).append(e)
    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent = [e for e in entries if e.rated_at and e.rated_at >= thirty_days_ago]
    recent.sort(key=lambda e: e.rated_at or datetime.min, reverse=True)

    lines = []
    label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    for mt, label in label_map.items():
        items = by_type.get(mt, [])[:8]
        if items:
            item_lines = [f"  - {e.title} — {e.rating}/10 [{e.genres or ''}]" for e in items]
            lines.append(f"{label}:\n" + "\n".join(item_lines))
    profile_summary = "\n\n".join(lines)

    recent_summary = ""
    if recent:
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/10)" for e in recent[:8]]
        recent_summary = f"\n\nRECENTLY RATED:\n" + "\n".join(recent_lines)

    try:
        from app.services.gemini import generate

        prompt = f"""Look at this person's cross-medium taste profile and generate 3 sharp, specific insights about patterns or connections. Focus on cross-medium discoveries — things that connect their book taste to their TV taste, or movies to podcasts.

{profile_summary}
{recent_summary}

Each insight should be ONE specific, non-generic observation. Bad examples: "You like drama" or "Your taste is eclectic". Good examples:
- "Your top-rated book (*The Road*) and your top-rated TV show (*The Last of Us*) both feature post-apocalyptic parent-child journeys"
- "You gravitate to unreliable narrators across books and films — from *Gone Girl* to *Shutter Island*"
- "Your recent ratings show a shift from propulsive thrillers toward meditative literary fiction"

Return ONLY valid JSON, no markdown:
{{
  "insights": [
    {{"icon": "connection|trend|pattern|shift", "text": "one specific insight referencing actual items from their profile"}},
    {{"icon": "...", "text": "..."}},
    {{"icon": "...", "text": "..."}}
  ]
}}

Icon choices:
- "connection" = cross-medium pattern (same theme across types)
- "trend" = overall direction of their taste
- "pattern" = recurring element
- "shift" = recent change in mood/focus"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        result = json.loads(text)
        cache.set(cache_key, result, ttl_seconds=86400)
        return result
    except Exception as e:
        log.error("insights failed: %s", str(e))
        return {"insights": []}


@router.get("/taste-dna")
async def taste_dna(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Generate an AI analysis of the user's taste across all media types. Cached 24h."""
    import json
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import MediaEntry

    cache_key = f"taste_dna:{user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.gemini_api_key:
        return {"themes": [], "moods": [], "tones": [], "summary": ""}

    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)).all()
    if len(entries) < 3:
        return {"themes": [], "moods": [], "tones": [], "summary": "Add and rate a few items to see your taste DNA."}

    # Group by type, top rated
    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    for e in entries:
        if e.rating and e.rating >= 6:
            by_type.setdefault(e.media_type, []).append(e)
    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    # Recent items
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent = [e for e in entries if e.rated_at and e.rated_at >= thirty_days_ago]
    recent.sort(key=lambda e: e.rated_at or datetime.min, reverse=True)

    lines = []
    label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    for mt, label in label_map.items():
        items = by_type.get(mt, [])[:10]
        if items:
            item_lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/10 [{e.genres or ''}]" for e in items]
            lines.append(f"{label}:\n" + "\n".join(item_lines))
    profile_summary = "\n\n".join(lines) if lines else ""

    recent_summary = ""
    if recent:
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/10)" for e in recent[:8]]
        recent_summary = f"\n\nRECENT MOOD (last 30 days):\n" + "\n".join(recent_lines)

    try:
        from app.services.gemini import generate

        prompt = f"""You are a taste analyst. Analyze this person's cross-medium taste profile and identify what makes them unique as a media consumer. Look for patterns across all media types — themes, tones, narrative structures — not just genres.

{profile_summary}
{recent_summary}

Return ONLY valid JSON, no markdown:
{{
  "themes": ["5-7 specific themes they gravitate to — e.g. 'morally complex anti-heroes', 'slow-burn character studies', 'unreliable narrators'"],
  "moods": ["4-6 emotional moods — e.g. 'melancholic', 'darkly comic', 'hopeful', 'atmospheric dread'"],
  "tones": ["3-5 narrative tones — e.g. 'literary', 'propulsive', 'meditative', 'maximalist'"],
  "summary": "One sharp paragraph (3-4 sentences) that captures who this person is as a media consumer. Reference specific items across DIFFERENT media types to show cross-medium patterns. Be specific and insightful, not generic.",
  "recent_shift": "One sentence about any mood shift in their recent engagement, or empty string if nothing stands out"
}}"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        result = json.loads(text)
        cache.set(cache_key, result, ttl_seconds=86400)
        return result
    except Exception as e:
        log.error("taste_dna failed: %s", str(e))
        return {"themes": [], "moods": [], "tones": [], "summary": "", "recent_shift": ""}


class TonightRequest(BaseModel):
    available_time: str  # e.g. "30 min", "1 hour", "2 hours", "evening", "weekend"
    mood: str | None = None


@router.post("/tonight")
async def tonight_pick(
    req: TonightRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Get one context-aware hero pick based on available time and mood."""
    import json
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import DismissedItem, MediaEntry
    from app.services.unified_search import unified_search

    import hashlib
    mood_hash = hashlib.md5((req.mood or "").encode()).hexdigest()[:8]
    time_slug = req.available_time.replace(" ", "_")
    cache_key = f"tonight:{user.id}:{time_slug}:{mood_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="AI features not configured")

    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    existing_titles = {e.title.lower() for e in entries}
    dismissed = {d.title.lower() for d in db.query(DismissedItem).filter(DismissedItem.user_id == user.id).all()}
    existing_titles = existing_titles | dismissed

    # Build cross-medium taste summary
    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_items = []
    for e in entries:
        if e.rating and e.rating >= 7:
            by_type.setdefault(e.media_type, []).append(e)
        if e.rated_at and e.rated_at >= thirty_days_ago and e.rating:
            recent_items.append(e)

    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    taste_sections = []
    labels = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    for mt, label in labels.items():
        items = by_type.get(mt, [])[:6]
        if items:
            lines = [f"  - {e.title} — {e.rating}/10" for e in items]
            taste_sections.append(f"{label}:\n" + "\n".join(lines))

    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    recent_text = ""
    if recent_items:
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/10)" for e in recent_items[:6]]
        recent_text = f"\n\nRECENTLY RATED (last 30 days):\n" + "\n".join(recent_lines)

    avoid_list = list(existing_titles)[:40]
    avoid_str = ", ".join(avoid_list) if avoid_list else "none"

    # Time-based guidance for the AI
    time_guidance = {
        "30 min": "a short podcast episode, a short film, or a TV episode under 30 minutes — NOT a book or movie",
        "1 hour": "a TV episode, a podcast episode, or a short film — NOT a full-length movie or book",
        "2 hours": "a movie (ideally around 90-120 minutes) OR a few TV episodes — NOT a long book",
        "evening": "a movie OR 2-3 TV episodes OR a few chapters of a book — any medium works",
        "weekend": "a full movie, a TV season to binge, or a book to start — go bold",
    }
    time_hint = time_guidance.get(req.available_time, "any medium is fine")

    try:
        from app.services.gemini import generate

        mood_line = f"\nCURRENT MOOD: {req.mood}" if req.mood else ""
        prompt = f"""You are NextUp, a cross-medium taste expert. Pick ONE perfect thing for this person to consume right now based on their taste, available time, and mood.

USER'S TASTE PROFILE:
{taste_summary}
{recent_text}

CONTEXT:
- Available time: {req.available_time}
- Time-appropriate media: {time_hint}{mood_line}

CRITICAL: The reason MUST cite at least ONE specific item from a DIFFERENT media type in their profile — that's the cross-medium signature of NextUp.

Do NOT recommend any of these titles (already in their library or dismissed): {avoid_str}

Return ONLY valid JSON, no markdown:
{{
  "title": "the one perfect pick",
  "media_type": "movie|tv|book|podcast",
  "year": 2020,
  "runtime_note": "e.g. '1h 55m' for movies, '~10 hour read' for books, '45 min episode' for TV, '~60 min' for podcast",
  "reason": "2-3 sentences explaining why this is PERFECT right now — citing specific items from their profile in a DIFFERENT media type"
}}"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        pick = json.loads(text)

        # Enrich with poster
        matches = await unified_search(pick.get("title", ""), pick.get("media_type"))
        matches = _rank_by_title_match(pick.get("title", ""), matches)
        if matches:
            best = matches[0]
            result = {
                "title": best.title,
                "media_type": best.media_type,
                "year": best.year,
                "image_url": best.image_url,
                "external_id": best.external_id,
                "source": best.source,
                "creator": best.creator,
                "genres": best.genres,
                "description": best.description,
                "runtime_note": pick.get("runtime_note", ""),
                "reason": pick.get("reason", ""),
            }
        else:
            result = {
                "title": pick.get("title", ""),
                "media_type": pick.get("media_type", "movie"),
                "year": pick.get("year"),
                "image_url": None,
                "external_id": "",
                "source": "",
                "creator": None,
                "genres": [],
                "description": None,
                "runtime_note": pick.get("runtime_note", ""),
                "reason": pick.get("reason", ""),
            }

        cache.set(cache_key, result, ttl_seconds=3600)  # 1 hour
        return result
    except json.JSONDecodeError as e:
        log.error("tonight_pick JSON parse failed: %s", str(e))
        raise HTTPException(status_code=500, detail="AI response format invalid, please try again")
    except HTTPException:
        raise
    except Exception as e:
        log.error("tonight_pick failed: %s", str(e))
        raise HTTPException(status_code=500, detail="Could not generate tonight pick")


@router.get("/top-picks")
async def top_picks(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get 4 personalized top recommendations with poster images. Cached per user."""
    import json

    from app import cache
    from app.config import settings
    from app.models import MediaEntry
    from app.services.unified_search import unified_search

    cache_key = f"top_picks:{user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.gemini_api_key:
        return []

    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "consumed").all()
    all_entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    existing_titles = {e.title.lower() for e in all_entries}

    # Also exclude dismissed items
    from app.models import DismissedItem
    dismissed_titles = {d.title.lower() for d in db.query(DismissedItem).filter(DismissedItem.user_id == user.id).all()}
    existing_titles = existing_titles | dismissed_titles

    # Build cross-medium taste summary, grouped by type and weighted by recency
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    recent_items = []
    for e in entries:
        if e.rating and e.rating >= 7:
            by_type.setdefault(e.media_type, []).append(e)
        # Use rated_at (active engagement) for recent mood, not created_at (bulk import time)
        if e.rated_at and e.rated_at >= thirty_days_ago and e.rating:
            recent_items.append(e)

    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    taste_sections = []
    type_labels = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    for mt, label in type_labels.items():
        items = by_type.get(mt, [])[:8]
        if items:
            lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/10 [{e.genres or ''}]" for e in items]
            taste_sections.append(f"{label} they rated highly:\n" + "\n".join(lines))

    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    recent_section = ""
    if recent_items:
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/10)" for e in recent_items[:10]]
        recent_section = f"\n\nRECENTLY RATED (last 30 days — their current mood, weight heavily):\n" + "\n".join(recent_lines)

    # Build a list of titles to avoid
    avoid_titles = list(existing_titles)[:50]
    avoid_str = ", ".join(avoid_titles) if avoid_titles else "none"

    try:
        from app.services.gemini import generate

        prompt = f"""You are a cross-medium taste expert. Your specialty is finding unexpected connections between books, TV, movies, and podcasts that share the same *essence* — theme, tone, narrative style, or emotional vibe — even when the genre differs.

USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}

TASK: Pick exactly 4 recommendations — ONE movie, ONE TV show, ONE book, ONE podcast.

CRITICAL REQUIREMENT: Each "reason" MUST explicitly cite at least ONE specific item from a DIFFERENT media type in their profile. This is what makes NextUp unique — we find cross-medium connections. Examples:

- "The atmospheric dread of *Dune* (book) translates directly to this slow-burn sci-fi film."
- "You loved the slow-burn character work of *The Wire* (TV) — this literary novel has the same patient, morally complex storytelling."
- "If *Serial* (podcast) hooked you on true crime, this documentary series is its visual counterpart."

Rules:
- 4 items exactly (movie, tv, book, podcast)
- Each reason MUST cite an item from a DIFFERENT media type by name (e.g., a book rec cites a movie/TV/podcast they loved)
- If recently consumed items suggest a mood shift, lean into that mood
- Do NOT recommend any of these (already in their library): {avoid_str}
- Pick bold, specific things they'll love — not generic bestsellers

Return ONLY valid JSON, no markdown:
[
  {{"title": "...", "media_type": "movie", "year": 2020, "reason": "Because you loved [BOOK/TV/PODCAST in their profile], this movie captures the same [specific quality]."}},
  {{"title": "...", "media_type": "tv", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "book", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "podcast", "year": 2020, "reason": "..."}}
]"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        picks = json.loads(text)

        # Search for each pick to get poster images — in parallel
        import asyncio

        async def search_pick(pick):
            title = pick.get("title", "")
            mt = pick.get("media_type", None)
            matches = await unified_search(title, mt)
            matches = _rank_by_title_match(title, matches)
            if matches:
                best = matches[0]
                return {
                    "title": best.title,
                    "media_type": best.media_type,
                    "year": best.year,
                    "image_url": best.image_url,
                    "external_id": best.external_id,
                    "source": best.source,
                    "description": best.description,
                    "reason": pick.get("reason", ""),
                    "genres": best.genres,
                }
            return {
                "title": title,
                "media_type": mt or "movie",
                "year": pick.get("year"),
                "image_url": None,
                "external_id": "",
                "source": "",
                "description": None,
                "reason": pick.get("reason", ""),
                "genres": [],
            }

        found = await asyncio.gather(*[search_pick(p) for p in picks[:4]])
        results = [r for r in found if r is not None and r["title"].lower() not in dismissed_titles]
        cache.set(cache_key, results, ttl_seconds=7200)
        return results
    except Exception as e:
        log.error("top_picks failed: %s", str(e))
        return []


@router.get("/suggestions/home")
async def home_suggestions(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get AI-powered suggestions for empty swim lanes. Cached per user."""
    import json

    from app import cache
    from app.config import settings
    from app.models import MediaEntry

    cache_key = f"suggestions_home:{user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    consumed = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "consumed").all()
    want = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume").all()

    from app.models import DismissedItem
    dismissed_titles = {d.title.lower() for d in db.query(DismissedItem).filter(DismissedItem.user_id == user.id).all()}

    # Figure out which types are missing from the queue
    queue_types = {item.media_type for item in want}
    all_types = {"movie", "tv", "book", "podcast"}
    missing_types = all_types - queue_types

    if not missing_types or not settings.gemini_api_key:
        return {"suggestions": {}}

    # Build cross-medium taste summary with recent weighting
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    recent_items = []
    for e in consumed:
        if e.rating and e.rating >= 7:
            by_type.setdefault(e.media_type, []).append(e)
        if e.rated_at and e.rated_at >= thirty_days_ago and e.rating:
            recent_items.append(e)

    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    taste_sections = []
    label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    for mt, label in label_map.items():
        items = by_type.get(mt, [])[:6]
        if items:
            lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/10" for e in items]
            taste_sections.append(f"{label}:\n" + "\n".join(lines))

    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    recent_section = ""
    if recent_items:
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/10)" for e in recent_items[:8]]
        recent_section = f"\n\nRECENTLY RATED (last 30 days — their current mood, weight heavily):\n" + "\n".join(recent_lines)

    type_labels = {"movie": "movies", "tv": "TV shows", "book": "books", "podcast": "podcasts"}
    missing_labels = [type_labels[t] for t in missing_types]

    try:
        from app.services.gemini import generate

        prompt = f"""You are a cross-medium taste expert. Find connections between books, TV, movies, and podcasts that share the same essence.

USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}

TASK: Suggest 3 items for EACH of these categories: {', '.join(missing_labels)}.

CRITICAL: Each "reason" MUST cite at least one specific item from a DIFFERENT media type in their profile. This cross-medium connection is essential. Example: "The slow-burn morality of [BOOK IN PROFILE] translates directly to this TV show."

Return ONLY valid JSON, no markdown:
{{
  "movie": [{{"title": "...", "year": 2020, "reason": "Because you loved [specific item from profile, different media type], ...", "predicted_rating": 8.5}}],
  "tv": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 8.5}}],
  "book": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 8.5}}],
  "podcast": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 8.5}}]
}}

predicted_rating is 1-10 based on how much this user would enjoy it.
Only include categories from this list: {', '.join(missing_types)}"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)

        # Search for poster images in parallel
        import asyncio

        from app.services.unified_search import unified_search

        async def enrich(item, media_type):
            title = item.get("title", "")
            pr = item.get("predicted_rating")
            matches = await unified_search(title, media_type)
            matches = _rank_by_title_match(title, matches)
            if matches:
                best = matches[0]
                return {
                    "title": best.title,
                    "year": best.year,
                    "reason": item.get("reason", ""),
                    "predicted_rating": pr,
                    "image_url": best.image_url,
                    "external_id": best.external_id,
                    "source": best.source,
                    "media_type": best.media_type,
                }
            return {
                "title": title,
                "year": item.get("year"),
                "reason": item.get("reason", ""),
                "predicted_rating": pr,
                "image_url": None,
                "external_id": "",
                "source": "",
                "media_type": media_type,
            }

        enriched = {}
        all_tasks = []
        task_keys = []
        for media_type, items in parsed.items():
            if not isinstance(items, list):
                continue
            for item in items:
                # Skip dismissed items before we make API calls
                if item.get("title", "").lower() in dismissed_titles:
                    continue
                all_tasks.append(enrich(item, media_type))
                task_keys.append(media_type)

        results = await asyncio.gather(*all_tasks)
        for key, result in zip(task_keys, results):
            if result["title"].lower() not in dismissed_titles:
                enriched.setdefault(key, []).append(result)

        result = {"suggestions": enriched}
        cache.set(cache_key, result, ttl_seconds=21600)
        return result
    except Exception as e:
        log.error("home_suggestions failed: %s", str(e))
        return {"suggestions": {}}


@router.get("/related/{media_type}/{external_id}")
async def related_items(
    media_type: str,
    external_id: str,
    source: str = "",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Get cross-medium related items for a given media item. Cached per-item."""
    import asyncio
    import json

    from app import cache
    from app.config import settings
    from app.models import MediaEntry
    from app.services.unified_search import get_detail, unified_search

    cache_key = f"related:{media_type}:{external_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.gemini_api_key:
        return {"related": {}, "adaptation": None}

    # Get the current item's details for context
    item = await get_detail(media_type, external_id, source)
    if not item:
        return {"related": {}, "adaptation": None}

    # Get the user's top-rated items for cross-medium personalization
    top_rated = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None))
        .order_by(MediaEntry.rating.desc())
        .limit(15)
        .all()
    )
    taste_lines = [f"- {e.title} ({e.media_type}, {e.rating}/10)" for e in top_rated] if top_rated else []
    taste_summary = "\n".join(taste_lines) if taste_lines else "no profile yet"

    # Figure out which media types to recommend (all except current)
    other_types = [mt for mt in ("movie", "tv", "book", "podcast") if mt != media_type]
    type_labels = {"movie": "movies", "tv": "TV shows", "book": "books", "podcast": "podcasts"}
    other_labels = [type_labels[t] for t in other_types]

    item_desc = item.description[:300] if item.description else ""
    item_genres = ", ".join(item.genres) if item.genres else ""

    try:
        from app.services.gemini import generate

        prompt = f"""You are a cross-medium taste expert. Given this media item, suggest 2 items from EACH OTHER media type that share the same essence — theme, tone, narrative style — not just genre.

CURRENT ITEM: {item.title} ({media_type}, {item.year or '?'})
Genres: {item_genres}
Description: {item_desc}

User's taste profile (for personalization):
{taste_summary}

TASK: Recommend 2 items each from: {', '.join(other_labels)}.

Also identify if this item has a direct adaptation in another medium (book→movie, movie→book, TV→book, etc.). If yes, include it in the "adaptation" field.

Each reason should explain the thematic/tonal connection, not just "also good".

Return ONLY valid JSON, no markdown:
{{
  "adaptation": {{"title": "...", "media_type": "movie|tv|book", "year": 2020, "note": "one sentence about the adaptation"}} OR null if no direct adaptation,
  "related": {{
    {', '.join([f'"{t}": [{{"title": "...", "year": 2020, "reason": "specific thematic/tonal connection"}}]' for t in other_types])}
  }}
}}"""

        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)

        # Enrich related items with posters via parallel search
        async def enrich(rel_item, rel_type):
            title = rel_item.get("title", "")
            matches = await unified_search(title, rel_type)
            matches = _rank_by_title_match(title, matches)
            if matches:
                best = matches[0]
                return {
                    "title": best.title, "year": best.year,
                    "image_url": best.image_url, "external_id": best.external_id,
                    "source": best.source, "media_type": best.media_type,
                    "reason": rel_item.get("reason", ""),
                }
            return {
                "title": title, "year": rel_item.get("year"),
                "image_url": None, "external_id": "", "source": "",
                "media_type": rel_type,
                "reason": rel_item.get("reason", ""),
            }

        enriched_related = {}
        tasks = []
        task_types = []
        for rel_type, items in parsed.get("related", {}).items():
            if not isinstance(items, list):
                continue
            for rel_item in items[:2]:
                tasks.append(enrich(rel_item, rel_type))
                task_types.append(rel_type)

        results = await asyncio.gather(*tasks) if tasks else []
        for rel_type, result in zip(task_types, results):
            enriched_related.setdefault(rel_type, []).append(result)

        # Enrich adaptation if present
        adaptation = parsed.get("adaptation")
        if adaptation and adaptation.get("title"):
            try:
                ad_matches = await unified_search(adaptation["title"], adaptation.get("media_type"))
                ad_matches = _rank_by_title_match(adaptation["title"], ad_matches)
                if ad_matches:
                    best = ad_matches[0]
                    adaptation = {
                        "title": best.title, "year": best.year,
                        "image_url": best.image_url, "external_id": best.external_id,
                        "source": best.source, "media_type": best.media_type,
                        "note": adaptation.get("note", ""),
                    }
            except Exception:
                pass

        result = {"related": enriched_related, "adaptation": adaptation}
        cache.set(cache_key, result, ttl_seconds=86400)
        return result
    except Exception as e:
        log.error("related_items failed: %s", str(e))
        return {"related": {}, "adaptation": None}


@router.get("/{media_type}/{external_id}")
async def get_media_detail(media_type: str, external_id: str, source: str = ""):
    """Get detailed info for a specific media item."""
    from app.services.unified_search import get_detail

    return await get_detail(media_type, external_id, source)
