from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
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
    """Search for multiple titles with explicit media types."""
    from app.services.unified_search import unified_search

    results = {}
    for item in req.items:
        title = item.title.strip()
        if not title:
            continue
        matches = await unified_search(title, item.media_type)
        matches = _rank_by_title_match(title, matches)
        results[title] = matches[:3] if matches else []

    return results


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


@router.get("/top-picks")
async def top_picks(db: Session = Depends(get_db)):
    """Get 3 personalized top recommendations with poster images."""
    import json

    from app.config import settings
    from app.models import MediaEntry
    from app.services.unified_search import unified_search

    if not settings.gemini_api_key:
        return []

    entries = db.query(MediaEntry).filter(MediaEntry.status == "consumed").all()
    existing_titles = {e.title.lower() for e in entries}

    # Build taste summary
    high_rated = sorted([e for e in entries if e.rating and e.rating >= 7], key=lambda e: e.rating, reverse=True)[:12]
    taste_lines = []
    for e in high_rated:
        taste_lines.append(f"- {e.title} ({e.media_type}, {e.year or '?'}) rated {e.rating}/10 [{e.genres or ''}]")

    taste_summary = "\n".join(taste_lines) if taste_lines else "No rated items yet — suggest 3 universally acclaimed picks across different media types."

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(model_name="gemini-3.1-flash-lite-preview")

        prompt = f"""You are a media recommendation expert. Based on this taste profile, pick the 3 BEST next things this person should watch, read, or listen to. Mix media types. Be specific and bold in your picks.

User's taste:
{taste_summary}

Return ONLY valid JSON — no markdown:
[
  {{"title": "...", "media_type": "movie|tv|book|podcast", "year": 2020, "reason": "one compelling sentence about why this is perfect for them"}}
]

Rules:
- Exactly 3 items
- Don't recommend anything they've already consumed
- Mix different media types if possible
- Pick things they'd LOVE, not just things that are popular"""

        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        picks = json.loads(text)

        # Search for each pick to get poster images
        results = []
        for pick in picks[:3]:
            title = pick.get("title", "")
            mt = pick.get("media_type", None)
            if title.lower() in existing_titles:
                continue
            matches = await unified_search(title, mt)
            matches = _rank_by_title_match(title, matches)
            if matches:
                best = matches[0]
                results.append({
                    "title": best.title,
                    "media_type": best.media_type,
                    "year": best.year,
                    "image_url": best.image_url,
                    "external_id": best.external_id,
                    "source": best.source,
                    "description": best.description,
                    "reason": pick.get("reason", ""),
                    "genres": best.genres,
                })
            else:
                results.append({
                    "title": title,
                    "media_type": mt or "movie",
                    "year": pick.get("year"),
                    "image_url": None,
                    "external_id": "",
                    "source": "",
                    "description": None,
                    "reason": pick.get("reason", ""),
                    "genres": [],
                })

        return results
    except Exception:
        return []


@router.get("/suggestions/home")
async def home_suggestions(db: Session = Depends(get_db)):
    """Get AI-powered suggestions for empty swim lanes on the home page."""
    import json

    from app.config import settings
    from app.models import MediaEntry

    consumed = db.query(MediaEntry).filter(MediaEntry.status == "consumed").all()
    want = db.query(MediaEntry).filter(MediaEntry.status == "want_to_consume").all()

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
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(model_name="gemini-3.1-flash-lite-preview")

        prompt = f"""Based on this user's taste profile, suggest 3 items for EACH of these categories: {', '.join(missing_labels)}.

User's highly rated items:
{taste_summary}

Return ONLY valid JSON with this structure — no markdown, no explanation:
{{
  "movie": [{{"title": "...", "year": 2020, "reason": "one short sentence"}}],
  "tv": [{{"title": "...", "year": 2020, "reason": "one short sentence"}}],
  "book": [{{"title": "...", "year": 2020, "reason": "one short sentence"}}],
  "podcast": [{{"title": "...", "year": 2020, "reason": "one short sentence"}}]
}}

Only include categories from this list: {', '.join(missing_types)}"""

        response = model.generate_content(prompt)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
        return {"suggestions": parsed}
    except Exception:
        return {"suggestions": {}}


@router.get("/{media_type}/{external_id}")
async def get_media_detail(media_type: str, external_id: str, source: str = ""):
    """Get detailed info for a specific media item."""
    from app.services.unified_search import get_detail

    return await get_detail(media_type, external_id, source)
