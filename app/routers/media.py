from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
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

    # Build taste summary
    high_rated = sorted([e for e in entries if e.rating and e.rating >= 7], key=lambda e: e.rating, reverse=True)[:12]
    taste_lines = []
    for e in high_rated:
        taste_lines.append(f"- {e.title} ({e.media_type}, {e.year or '?'}) rated {e.rating}/10 [{e.genres or ''}]")

    taste_summary = "\n".join(taste_lines) if taste_lines else "No rated items yet — suggest universally acclaimed picks across different media types."

    # Build a list of titles to avoid
    avoid_titles = list(existing_titles)[:50]
    avoid_str = ", ".join(avoid_titles) if avoid_titles else "none"

    try:
        from app.services.gemini import generate

        prompt = f"""You are a media recommendation expert. Based on this taste profile, pick the BEST next thing this person should try in EACH of these 4 categories. Be specific and bold.

User's taste:
{taste_summary}

Return ONLY valid JSON — no markdown:
[
  {{"title": "...", "media_type": "movie", "year": 2020, "reason": "one compelling sentence about why this is perfect for them"}},
  {{"title": "...", "media_type": "tv", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "book", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "podcast", "year": 2020, "reason": "..."}}
]

Rules:
- Exactly 4 items — one movie, one TV show, one book, one podcast
- Do NOT recommend any of these titles (already in their library): {avoid_str}
- Pick things they'd LOVE, not just things that are popular"""

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
    except Exception:
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

    # Build a brief taste summary
    taste_lines = []
    high_rated = sorted([e for e in consumed if e.rating and e.rating >= 7], key=lambda e: e.rating, reverse=True)[:10]
    for e in high_rated:
        taste_lines.append(f"- {e.title} ({e.media_type}, {e.year or '?'}) rated {e.rating}/10")

    taste_summary = "\n".join(taste_lines) if taste_lines else "No rated items yet — suggest popular, well-regarded picks."

    type_labels = {"movie": "movies", "tv": "TV shows", "book": "books", "podcast": "podcasts"}
    missing_labels = [type_labels[t] for t in missing_types]

    try:
        from app.services.gemini import generate

        prompt = f"""Based on this user's taste profile, suggest 3 items for EACH of these categories: {', '.join(missing_labels)}.

User's highly rated items:
{taste_summary}

Return ONLY valid JSON with this structure — no markdown, no explanation:
{{
  "movie": [{{"title": "...", "year": 2020, "reason": "one short sentence", "predicted_rating": 8.5}}],
  "tv": [{{"title": "...", "year": 2020, "reason": "one short sentence", "predicted_rating": 8.5}}],
  "book": [{{"title": "...", "year": 2020, "reason": "one short sentence", "predicted_rating": 8.5}}],
  "podcast": [{{"title": "...", "year": 2020, "reason": "one short sentence", "predicted_rating": 8.5}}]
}}

predicted_rating should be 1-10 based on how much this user would enjoy it.
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
                all_tasks.append(enrich(item, media_type))
                task_keys.append(media_type)

        results = await asyncio.gather(*all_tasks)
        for key, result in zip(task_keys, results):
            if result["title"].lower() not in dismissed_titles:
                enriched.setdefault(key, []).append(result)

        result = {"suggestions": enriched}
        cache.set(cache_key, result, ttl_seconds=21600)
        return result
    except Exception:
        return {"suggestions": {}}


@router.get("/{media_type}/{external_id}")
async def get_media_detail(media_type: str, external_id: str, source: str = ""):
    """Get detailed info for a specific media item."""
    from app.services.unified_search import get_detail

    return await get_detail(media_type, external_id, source)
