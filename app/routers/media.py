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
    """Rank search results by title similarity, breaking ties on whether
    a poster/cover exists. For common titles — especially books on Open
    Library — the top title match often lacks a cover because multiple
    editions exist; prefer the edition with an image so cards render."""
    query_lower = query.lower().strip()

    def title_score(item: MediaResult) -> float:
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

    def sort_key(item: MediaResult) -> tuple:
        # Primary: title score. Secondary: has image (1 if yes, 0 if no).
        # Both descending via negation so sorted() ascending works.
        return (-title_score(item), 0 if item.image_url else 1)

    return sorted(results, key=sort_key)


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
async def taste_dna(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    refresh: bool = Query(False),
):
    """Generate an AI analysis of the user's taste across all media types. Cached 24h."""
    import json
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import DismissedItem, MediaEntry

    cache_key = f"taste_dna:{user.id}"
    if refresh:
        cache.invalidate(cache_key)
    else:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    if not settings.gemini_api_key:
        return {"themes": [], "summary": "", "by_medium": {}, "signature_items": [], "avoided": "", "recent_shift": ""}

    # Pull ALL entries — unrated items (esp. from bulk imports) are still a signal:
    # the user deliberately added/shelved them.
    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    if len(entries) < 3:
        return {"themes": [], "summary": "Add at least a few items to see your taste DNA.", "by_medium": {}, "signature_items": [], "avoided": "", "recent_shift": ""}

    # Partition: loved (rated 8+), liked (6-7), consumed-unrated, queued (want_to_consume), low-rated
    loved = sorted([e for e in entries if e.rating and e.rating >= 8], key=lambda e: e.rating or 0, reverse=True)
    liked = sorted([e for e in entries if e.rating and 6 <= e.rating <= 7], key=lambda e: e.rating or 0, reverse=True)
    consumed_unrated = [e for e in entries if e.status == "consumed" and not e.rating]
    queued = [e for e in entries if e.status == "want_to_consume"]
    low_rated = sorted([e for e in entries if e.rating and e.rating <= 4], key=lambda e: e.rating or 0)[:10]

    # Recent items — rated OR added
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent = [e for e in entries if (e.rated_at and e.rated_at >= thirty_days_ago) or (e.created_at and e.created_at >= thirty_days_ago)]
    recent.sort(key=lambda e: (e.rated_at or e.created_at or datetime.min), reverse=True)

    dismissed = db.query(DismissedItem.title, DismissedItem.media_type).filter(DismissedItem.user_id == user.id).all()

    # Genre frequency across ALL items (unrated included)
    genre_counts: dict[str, int] = {}
    for e in entries:
        if e.genres:
            for g in e.genres.split(","):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1
    top_genres = sorted(genre_counts, key=lambda k: genre_counts[k], reverse=True)[:12]

    # Totals per type
    type_totals: dict[str, int] = {}
    for e in entries:
        type_totals[e.media_type] = type_totals.get(e.media_type, 0) + 1

    # Build per-type prompt sections — prefer loved, then liked, then consumed-unrated, then queued
    def _sample(items: list, n: int) -> list:
        return items[:n]

    label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    lines = []
    for mt, label in label_map.items():
        total = type_totals.get(mt, 0)
        if total == 0:
            continue
        mt_loved = [e for e in loved if e.media_type == mt]
        mt_liked = [e for e in liked if e.media_type == mt]
        mt_consumed = [e for e in consumed_unrated if e.media_type == mt]
        mt_queued = [e for e in queued if e.media_type == mt]

        block = [f"{label} ({total} total):"]
        if mt_loved:
            block.append("  Loved (8+/10):")
            for e in _sample(mt_loved, 10):
                block.append(f"    - {e.title} ({e.year or '?'}) — {e.rating}/10 [{e.genres or ''}]")
        if mt_liked:
            block.append("  Liked (6-7/10):")
            for e in _sample(mt_liked, 6):
                block.append(f"    - {e.title} ({e.year or '?'}) — {e.rating}/10 [{e.genres or ''}]")
        if mt_consumed:
            block.append(f"  Finished but not rated ({len(mt_consumed)} total — strong signal, they chose to consume these):")
            for e in _sample(mt_consumed, 12):
                block.append(f"    - {e.title} ({e.year or '?'}) [{e.genres or ''}]")
        if mt_queued:
            block.append(f"  In their queue / want to consume ({len(mt_queued)} total — reflects aspirational taste):")
            for e in _sample(mt_queued, 10):
                block.append(f"    - {e.title} ({e.year or '?'}) [{e.genres or ''}]")
        lines.append("\n".join(block))
    profile_summary = "\n\n".join(lines) if lines else ""

    if top_genres:
        profile_summary += f"\n\nMOST COMMON GENRES across all items: {', '.join(top_genres)}"

    recent_summary = ""
    if recent:
        recent_lines = []
        for e in recent[:10]:
            rating_str = f", {e.rating}/10" if e.rating else ""
            recent_lines.append(f"  - {e.title} ({e.media_type}{rating_str})")
        recent_summary = "\n\nRECENT MOOD (last 30 days, rated or added):\n" + "\n".join(recent_lines)

    avoided_summary = ""
    if low_rated or dismissed:
        avoided_lines = [f"  - {e.title} ({e.media_type}) — rated {e.rating}/10" for e in low_rated[:6]]
        avoided_lines += [f"  - {row[0]} ({row[1]}) — dismissed" for row in list(dismissed)[:6]]
        if avoided_lines:
            avoided_summary = "\n\nITEMS THEY LOW-RATED OR DISMISSED:\n" + "\n".join(avoided_lines)

    try:
        from app.services.gemini import generate

        prompt = f"""You are a taste analyst writing a personalized taste profile for this user. Be insightful and specific — not generic. Reference actual items from their profile.

{profile_summary}
{recent_summary}
{avoided_summary}

IMPORTANT INSTRUCTIONS about the data you're seeing:
- "Loved (8+/10)" items are the strongest signal of taste — weight these heaviest.
- "Finished but not rated" items are real signal too: the user deliberately added AND consumed them. Hundreds of bulk-imported books with no ratings still reveal genre, author, and subject-matter preferences. DO NOT say "not enough info" just because ratings are sparse — the sheer set of items they chose to read/watch is itself the profile.
- "In their queue" items show aspirational taste — what they want to engage with.
- If one medium has many items but few ratings, infer from titles, genres, and authors directly.

This user may consume a mix of fiction and nonfiction. Pay attention to:
- Whether they read literary fiction, genre fiction, memoirs, idea books, narrative nonfiction
- Whether their movies include documentaries
- Whether their podcasts are narrative/storytelling or interview/explainer/news
The themes should capture BOTH what they read/watch for story AND what they consume for ideas or insight. Don't force everything into "narrative essence" framing if their profile is idea-driven.

For "avoided": Only describe genuine patterns of avoidance based on consistent low ratings in a specific direction. Don't claim they "avoid self-help" just because they rated one poorly, or "avoid nonfiction" if they actually read memoirs. Be specific or leave it empty.

Return ONLY valid JSON, no markdown. Each theme MUST include 2-3 example items from their actual profile that exemplify it:

{{
  "summary": "A 4-5 sentence essay capturing who this person is as a media consumer. Write in second person ('You gravitate to...'). Be specific, reference items across different media types, show cross-medium patterns. If they read both fiction and nonfiction, reflect that. No generic platitudes.",
  "themes": [
    {{"name": "specific theme like 'morally complex anti-heroes' or 'systems thinking about human behavior'", "description": "one-sentence explanation", "examples": ["exact item title from profile", "another exact item title", "a third if available"]}},
    ... 4-5 themes total
  ],
  "by_medium": {{
    "movie": "One sentence: what their movie taste reveals about them specifically (reference 1-2 movie titles from their profile, note if they lean fiction or documentary). Empty string if no movies.",
    "tv": "One sentence about their TV taste with example titles. Empty string if no TV.",
    "book": "One sentence about their book taste with example titles (note the fiction/nonfiction mix explicitly if relevant). Empty string if no books.",
    "podcast": "One sentence about their podcast taste — note if it's narrative, interview, or explainer-focused. Empty string if no podcasts."
  }},
  "signature_items": ["3-5 exact item titles from their profile that best define them — items you'd point to and say 'this person'"],
  "avoided": "One sentence describing a real, specific pattern they don't engage with — only if genuinely evident. Empty string if nothing clear stands out.",
  "recent_shift": "One sentence about any mood/theme shift in their last 30 days, or empty string."
}}"""

        log.info("taste_dna prompt length: %d chars, entries: %d (loved=%d, liked=%d, consumed_unrated=%d, queued=%d)",
                 len(prompt), len(entries), len(loved), len(liked), len(consumed_unrated), len(queued))
        text = (await generate(prompt)).strip()
        if not text:
            log.error("taste_dna: Gemini returned empty text")
            return {
                "themes": [],
                "summary": "The AI analyzer returned an empty response. Try again in a moment, or check server logs.",
                "by_medium": {},
                "signature_items": [],
                "avoided": "",
                "recent_shift": "",
                "error": "empty_ai_response",
            }

        # Robust JSON extraction — strip markdown fences and grab the first {...} block
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        # Fall back to finding the outermost JSON object
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]

        try:
            result = json.loads(text)
        except json.JSONDecodeError as je:
            log.error("taste_dna JSON parse failed: %s — response snippet: %s", str(je), text[:400])
            return {
                "themes": [],
                "summary": "The AI returned a response we couldn't parse. Try 'Re-analyze my taste' again.",
                "by_medium": {},
                "signature_items": [],
                "avoided": "",
                "recent_shift": "",
                "error": "json_parse_failed",
            }

        # Normalize: ensure top-level keys exist so the template renders something
        result.setdefault("themes", [])
        result.setdefault("summary", "")
        result.setdefault("by_medium", {})
        result.setdefault("signature_items", [])
        result.setdefault("avoided", "")
        result.setdefault("recent_shift", "")
        cache.set(cache_key, result, ttl_seconds=86400)
        return result
    except Exception as e:
        log.exception("taste_dna failed")
        return {
            "themes": [],
            "summary": f"Analyzer error: {str(e)[:200]}",
            "by_medium": {},
            "signature_items": [],
            "avoided": "",
            "recent_shift": "",
            "error": "exception",
        }


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
    dismissed = {row[0].lower() for row in db.query(DismissedItem.title).filter(DismissedItem.user_id == user.id).all()}
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
        prompt = f"""You are NextUp, a cross-medium taste expert. Pick ONE perfect thing — fiction or nonfiction — for this person to consume right now based on their taste, available time, and mood.

USER'S TASTE PROFILE:
{taste_summary}
{recent_text}

CONTEXT:
- Available time: {req.available_time}
- Time-appropriate media: {time_hint}{mood_line}

NONFICTION IS WELCOME: documentaries, memoirs, idea books, interview/explainer podcasts, narrative nonfiction — all valid. Match the user's fiction/nonfiction balance.

CRITICAL: The reason MUST cite at least ONE specific item from a DIFFERENT media type in their profile by name, and the connection must be a concrete theme/idea/tone — not a surface-level shared setting or keyword.

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
    dismissed_titles = {row[0].lower() for row in db.query(DismissedItem.title).filter(DismissedItem.user_id == user.id).all()}
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

        prompt = f"""You are a cross-medium taste expert. Your specialty is finding specific, real connections between books, TV, movies, and podcasts — fiction AND nonfiction — that share themes, ideas, tone, subject matter, or emotional register.

USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}

TASK: Pick exactly 4 recommendations — ONE movie, ONE TV show, ONE book, ONE podcast.

NONFICTION IS WELCOME:
- Movies can include documentaries (*My Octopus Teacher*, *The Social Dilemma*)
- Books can be literary nonfiction, memoirs, idea books, essays (*Sapiens*, *Educated*, *The Body Keeps the Score*)
- Podcasts can be interview, science, news, explainer (*Radiolab*, *The Daily*, *Hidden Brain*, *Ezra Klein Show*)
- Look at the user's profile — if they rate nonfiction or documentaries highly, recommend more of it. If they lean narrative, lean that way.

CRITICAL REQUIREMENT: Each "reason" MUST explicitly cite at least ONE specific item from a DIFFERENT media type in their profile. Good examples:
- "The atmospheric dread of *Dune* (book) translates directly to this slow-burn sci-fi film."
- "You loved the careful character work in *The Wire* (TV) — this nonfiction book has the same patient, morally complex portrait of institutional failure."
- "If *Serial* (podcast) hooked you on ambiguity and moral inquiry, this documentary explores similar unresolved tension."
- "You gave *Educated* (book) a 9/10 — this film has the same aching quality of a young person finding their own voice against the weight of their family."

Rules:
- 4 items exactly (movie, tv, book, podcast)
- Each reason MUST cite an item from a DIFFERENT media type by name
- The connection must be CONCRETE — cite a shared theme, idea, emotional beat, or narrative approach. Never rely on shared demographic, setting, or keyword.
- If recently rated items suggest a mood shift, lean into that mood
- Do NOT recommend any of these (already in their library): {avoid_str}
- Pick bold, specific things they'll love — not generic bestsellers

Return ONLY valid JSON, no markdown:
[
  {{"title": "...", "media_type": "movie", "year": 2020, "reason": "Because you loved [SPECIFIC ITEM in their profile, different media type], this captures the same [specific, concrete quality]."}},
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
    dismissed_titles = {row[0].lower() for row in db.query(DismissedItem.title).filter(DismissedItem.user_id == user.id).all()}

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

        prompt = f"""You are a cross-medium taste expert. Find connections between books, TV, movies, and podcasts — fiction AND nonfiction — that share themes, ideas, tone, or emotional register.

USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}

TASK: Suggest 3 items for EACH of these categories: {', '.join(missing_labels)}.

NONFICTION IS WELCOME:
- Movies include documentaries
- Books include memoirs, essays, idea books, narrative nonfiction
- Podcasts include interview, science, explainer, news
Look at the user's profile and match their fiction/nonfiction balance.

CRITICAL: Each "reason" MUST cite at least one specific item from a DIFFERENT media type in their profile AND name a CONCRETE shared element (theme, idea, emotional register, subject). Never match on surface features like setting, demographic, or keyword alone.

Good example: "You gave *The Wire* (TV) a 10/10 — this nonfiction book on the war on drugs delivers the same unflinching institutional critique."
Bad example: "Both are about cities."

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

        prompt = f"""You are a cross-medium taste expert. Given this media item, suggest 2 items from EACH OTHER media type that share a real, specific connection — theme, tone, subject matter, emotional register, ideas, or storytelling approach.

CURRENT ITEM: {item.title} ({media_type}, {item.year or '?'})
Genres: {item_genres}
Description: {item_desc}

User's taste profile (for personalization):
{taste_summary}

TASK: Recommend 2 items each from: {', '.join(other_labels)}.

WHAT COUNTS AS A MEDIA ITEM (all valid):
- Fiction: novels, narrative films, scripted TV, storytelling podcasts
- Literary nonfiction: memoirs, biographies, essays, narrative journalism
- Idea books / popular nonfiction: *Sapiens*, *Atomic Habits*, *The Body Keeps the Score*
- Documentaries: *My Octopus Teacher*, *The Vow*, nature docs, true crime docs
- News, science, interview, and explanatory podcasts: *Radiolab*, *The Daily*, *Hidden Brain*
- Self-help and philosophy books are fine IF they match thematically

WHAT TO AVOID: Pure reference/instructional material with no thematic voice — SAT prep, dictionaries, textbooks, software manuals, cookbooks without narrative. Don't recommend these unless the current item is also reference material.

CONNECTION RULES — this is the most important part:
1. The connection MUST be real and specific. Reference a CONCRETE element from the current item.
2. Cross-medium connections can span fiction and nonfiction BOTH WAYS:
   - A memoir about self-discovery can connect to a coming-of-age film
   - A documentary about loneliness can connect to a literary novel about isolation
   - A science podcast about the brain can connect to a thriller novel about memory
   - A nature doc can connect to a contemplative book about attention
3. GOOD example: "*Lady Bird* captures the raw self-consciousness of becoming yourself; Tara Westover's memoir *Educated* has that same aching specificity of a young woman learning to claim her own identity."
4. BAD example: "Both are about young women." — surface-level, no real connection.
5. BAD example: "This SAT prep book is for high schoolers." — keyword match, not thematic.
6. If you can't find a strong match for a type, return fewer items rather than reaching.
7. NEVER recommend based on shared setting, shared demographic, or shared keyword alone.

ADAPTATION: If the current item has a direct adaptation in another medium, include it.

Return ONLY valid JSON, no markdown:
{{
  "adaptation": {{"title": "...", "media_type": "movie|tv|book", "year": 2020, "note": "one sentence about the adaptation"}} OR null if no direct adaptation,
  "related": {{
    {', '.join([f'"{t}": [{{"title": "...", "year": 2020, "reason": "specific thematic/idea connection citing a concrete element from the current item"}}]' for t in other_types])}
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
