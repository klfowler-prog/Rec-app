import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user

log = logging.getLogger(__name__)
from app.database import get_db
from app.models import MediaEntry, User
from app.schemas import MediaResult

router = APIRouter()


@router.get("/search", response_model=list[MediaResult])
async def search_media(q: str = Query(..., min_length=1), media_type: str | None = None, user: User = Depends(require_user)):
    """Search across all media APIs."""
    from app.services.unified_search import unified_search

    return await unified_search(q, media_type)


class BulkSearchItem(BaseModel):
    title: str
    media_type: str


class BulkSearchRequest(BaseModel):
    items: list[BulkSearchItem]


@router.post("/bulk-search")
async def bulk_search(req: BulkSearchRequest, user: User = Depends(require_user)):
    """Search for multiple titles with explicit media types.

    Uses a semaphore to cap concurrency at 5, preventing API rate-limit
    failures that silently drop entire categories (e.g. books).
    """
    import asyncio

    from app.services.unified_search import unified_search

    items = [(item.title.strip(), item.media_type) for item in req.items if item.title.strip()]
    if not items:
        return {}

    sem = asyncio.Semaphore(5)

    async def search_one(title, media_type):
        async with sem:
            try:
                matches = await unified_search(title, media_type)
                matches = _rank_by_title_match(title, matches)
                return title, {"results": matches[:3] if matches else [], "error": False}
            except Exception:
                return title, {"results": [], "error": True}

    found = await asyncio.gather(*[search_one(t, mt) for t, mt in items])
    return {title: matches for title, matches in found}


def _rank_by_title_match(query: str, results: list[MediaResult], prefer_type: str | None = None) -> list[MediaResult]:
    """Rank search results by title similarity, breaking ties on whether
    a poster/cover exists and whether the media type matches the expected
    type. This prevents movie/TV confusion when both exist with the same
    title (e.g. Sharp Objects TV miniseries vs obscure movie)."""
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
        ts = title_score(item)
        # Boost items matching the expected media type
        type_match = 0 if (prefer_type and item.media_type == prefer_type) else 1
        has_image = 0 if item.image_url else 1
        return (-ts, type_match, has_image)

    return sorted(results, key=sort_key)


def _normalize_title(t: str) -> str:
    """Normalize a title for comparison so that minor variations — case,
    smart quotes, em-dashes, parenthetical subtitles, leading articles,
    unicode form — all collapse to the same key. Used by recommendation
    endpoints to check whether an AI-suggested or API-returned title
    is already in the user's library or dismissed list."""
    if not t:
        return ""
    import re
    import unicodedata

    # NFKD folds compatibility forms and decomposes accents. Strip the
    # combining marks so "café" matches "cafe" and NFC matches NFD.
    s = unicodedata.normalize("NFKD", t)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()

    # Drop parenthetical subtitles like "Hackquire (A Startup Story)"
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\[[^\]]*\]", " ", s)

    # Drop subtitle after a colon OR em/en dash so
    # "The Body Keeps the Score: Brain, Mind, and Body" matches
    # "The Body Keeps the Score" and "Name — Subtitle" matches "Name".
    for sep in (":", " — ", " – ", " - "):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break

    # Drop leading articles
    for article in ("the ", "a ", "an "):
        if s.startswith(article):
            s = s[len(article):]
            break

    # Strip punctuation and collapse whitespace
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_known_titles(db: Session, user_id: int) -> tuple[set[str], list[str]]:
    """Return (normalized_set, display_list) of everything the user has
    already engaged with or dismissed — consumed, consuming, queued, or
    explicitly dismissed. The normalized set is used for post-filtering
    AI suggestions; the display list is used in prompts."""
    from app.models import DismissedItem, MediaEntry

    rows = db.query(MediaEntry.title).filter(MediaEntry.user_id == user_id).all()
    dismissed_rows = db.query(DismissedItem.title).filter(DismissedItem.user_id == user_id).all()

    display: list[str] = []
    normalized: set[str] = set()
    for (title,) in rows:
        if not title:
            continue
        display.append(title)
        normalized.add(_normalize_title(title))
    for (title,) in dismissed_rows:
        if not title:
            continue
        display.append(title)
        normalized.add(_normalize_title(title))

    return normalized, display


def _is_known(title: str, known_normalized: set[str]) -> bool:
    return _normalize_title(title) in known_normalized


def _parse_ai_json(text: str, context: str) -> dict | list | None:
    """Robust parser for Gemini responses that are supposed to be JSON.

    Handles:
      - Markdown fences (``` or ```json)
      - Leading/trailing preamble around the actual JSON
      - Empty responses
      - JSONDecodeError with diagnostic logging including a snippet

    Returns None on any failure — the caller should treat None as
    "Gemini returned nothing we can use" and fall back to an empty
    result. Context string is used in log messages so we can tell
    which endpoint failed from Cloud Run logs."""
    import json

    if not text:
        log.error("%s: Gemini returned empty text", context)
        return None

    s = text.strip()
    # Strip markdown fences in either form
    if s.startswith("```"):
        # Drop first line (```json or ```)
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0]

    # Fall back to first balanced brace / bracket block so leading or
    # trailing prose doesn't break the parse.
    def _slice_between(s: str, open_c: str, close_c: str) -> str | None:
        first = s.find(open_c)
        last = s.rfind(close_c)
        if first >= 0 and last > first:
            return s[first : last + 1]
        return None

    # Try object-shaped first, then array-shaped. The JSON-shaped prompts
    # we use are all one or the other.
    obj_slice = _slice_between(s, "{", "}")
    arr_slice = _slice_between(s, "[", "]")
    # Prefer whichever is larger — the outer shape of the response.
    candidate = s
    if obj_slice and arr_slice:
        candidate = obj_slice if len(obj_slice) >= len(arr_slice) else arr_slice
    elif obj_slice:
        candidate = obj_slice
    elif arr_slice:
        candidate = arr_slice

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as je:
        log.error(
            "%s: JSON parse failed — %s — snippet: %s",
            context, str(je), candidate[:400],
        )
        return None


# ---------------------------------------------------------------------------
# Home-page "resonance" signal
#
# The new home page lets the user tap a currently-consuming chip to mark it
# as "what's resonating most right now". That signal gets stored under a
# subkey of UserPreferences.quiz_results (a JSON Text column we already have)
# so we don't need a schema migration, and decays after 14 days so stale
# signals don't bias future recs forever. The signal is injected into rec
# prompts via build_resonance_block().
# ---------------------------------------------------------------------------

_RESONANCE_KEY = "_home_resonance"
_RESONANCE_MAX_AGE_DAYS = 14


def _load_prefs_json(db: Session, user_id: int) -> tuple[object, dict]:
    """Load UserPreferences row + parsed quiz_results JSON for a user.
    Returns (prefs_row_or_none, parsed_dict). The parsed dict is always
    a dict, even if quiz_results is None or malformed, so callers can
    treat it as safe to mutate before writing back."""
    import json

    from app.models import UserPreferences

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not prefs or not prefs.quiz_results:
        return prefs, {}
    try:
        data = json.loads(prefs.quiz_results)
        return prefs, data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return prefs, {}


def get_home_resonance(db: Session, user_id: int) -> dict[str, str]:
    """Return a dict of {entry_id_str: iso_timestamp} for the user's
    currently active resonance signals. Expired entries (older than
    _RESONANCE_MAX_AGE_DAYS) are filtered out."""
    from datetime import datetime, timedelta

    _, data = _load_prefs_json(db, user_id)
    resonance = data.get(_RESONANCE_KEY) or {}
    if not isinstance(resonance, dict):
        return {}
    cutoff = datetime.utcnow() - timedelta(days=_RESONANCE_MAX_AGE_DAYS)
    fresh: dict[str, str] = {}
    for eid, ts in resonance.items():
        try:
            when = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            continue
        if when >= cutoff:
            fresh[str(eid)] = ts
    return fresh


def toggle_home_resonance(db: Session, user_id: int, entry_id: int) -> bool:
    """Toggle a resonance flag for (user, entry_id). Returns the new
    state (True = resonating, False = off). Writes back to
    UserPreferences.quiz_results under _RESONANCE_KEY."""
    import json
    from datetime import datetime

    from app.models import UserPreferences

    prefs, data = _load_prefs_json(db, user_id)
    resonance = data.get(_RESONANCE_KEY) or {}
    if not isinstance(resonance, dict):
        resonance = {}

    key = str(entry_id)
    new_state: bool
    if key in resonance:
        del resonance[key]
        new_state = False
    else:
        resonance[key] = datetime.utcnow().isoformat()
        new_state = True

    data[_RESONANCE_KEY] = resonance
    if prefs is None:
        prefs = UserPreferences(user_id=user_id, quiz_results=json.dumps(data))
        db.add(prefs)
    else:
        prefs.quiz_results = json.dumps(data)
    db.commit()
    return new_state


def build_resonance_block(db: Session, user_id: int) -> str:
    """Return a short prompt block describing which currently-consuming
    items the user has flagged as 'what's resonating most right now'.
    Empty string when there's no active signal. Used by home-bundle,
    best-bet, and recommend prompts to lean recs toward the texture
    of the flagged items."""
    from app.models import MediaEntry

    resonance = get_home_resonance(db, user_id)
    if not resonance:
        return ""
    ids = [int(k) for k in resonance.keys() if str(k).isdigit()]
    if not ids:
        return ""
    rows = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user_id, MediaEntry.id.in_(ids))
        .all()
    )
    if not rows:
        return ""
    lines = []
    for e in rows:
        genre_hint = f" [{e.genres}]" if e.genres else ""
        lines.append(f"  - {e.title} ({e.media_type}){genre_hint}")
    return (
        "RESONATING RIGHT NOW (the user has flagged these as what's "
        "hitting hardest in their current run — lean toward work that "
        "shares their specific texture, not just the same genre):\n"
        + "\n".join(lines)
        + "\n"
    )


def build_rec_feedback_block(db: Session, user_id: int) -> str:
    """Build a prompt block showing recent rec outcomes so the AI can
    learn from what worked and what didn't for this specific user."""
    from app.models import RecEvent

    recent = (
        db.query(RecEvent)
        .filter(RecEvent.user_id == user_id, RecEvent.outcome.isnot(None))
        .order_by(RecEvent.acted_at.desc())
        .limit(20)
        .all()
    )
    if not recent:
        return ""

    hits = []
    misses = []
    for e in recent:
        if e.outcome == "dismissed":
            misses.append(f"  - {e.title} ({e.media_type}) — dismissed")
        elif e.outcome == "consumed" and e.user_rating and e.user_rating >= 4:
            hits.append(f"  - {e.title} ({e.media_type}) — rated {e.user_rating}/5")
        elif e.outcome in ("saved", "started"):
            hits.append(f"  - {e.title} ({e.media_type}) — {e.outcome}")
        elif e.outcome == "consumed" and e.user_rating and e.user_rating <= 2:
            misses.append(f"  - {e.title} ({e.media_type}) — rated {e.user_rating}/5")

    if not hits and not misses:
        return ""

    lines = ["RECOMMENDATION TRACK RECORD (how past recs landed for this user — calibrate accordingly):"]
    if hits:
        lines.append("Recs that hit:")
        lines.extend(hits[:8])
    if misses:
        lines.append("Recs that missed:")
        lines.extend(misses[:8])
    return "\n".join(lines) + "\n"


@router.get("/trending/{media_type}")
async def get_trending(media_type: str = "all", limit: int = 10):
    """Get trending movies/TV from TMDB."""
    from app.services.tmdb import get_trending

    return await get_trending(media_type, "week", limit)


@router.get("/quiz-items")
async def quiz_items(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get a curated mix of well-known items across genres for the
    taste quiz. The underlying item catalog is shared across all users
    (expensive to fetch), but the response is then filtered against
    THIS user's profile so anything they've already rated — including
    items they just rated via the this-or-that section on the same
    page — is removed. Fixes the dupe-between-taste-test-and-quiz bug
    where the same item could appear in both sections."""
    import asyncio

    from app import cache
    from app.services.tmdb import search as tmdb_search
    from app.services.unified_search import search_books
    from app.services.itunes import search as search_podcasts

    # Shared base catalog — resolved external items, not filtered.
    cached = cache.get("quiz_items_base")
    if cached is not None:
        return _filter_quiz_items_for_user(cached, db, user.id)

    # Curated quiz items — intentionally span different TASTE REGIONS so
    # the AI can tell whether this person is a blockbuster fan, an
    # art-house devotee, a sitcom comfort-watcher, a silly-comedy lover,
    # a literary reader, a genre reader, etc. Lists below are grouped
    # into loose "regions" in comments so future edits stay balanced.
    movie_titles = [
        # Blockbusters / big studio crowd-pleasers
        "Avengers: Endgame", "Top Gun: Maverick", "Jurassic Park", "The Dark Knight",
        "Mission: Impossible - Fallout", "Inception",
        # Silly / broad comedy
        "Step Brothers", "Anchorman", "Superbad", "Bridesmaids", "Mean Girls",
        # Prestige drama
        "The Godfather", "Goodfellas", "No Country for Old Men", "There Will Be Blood",
        "Moonlight", "The Social Network",
        # Art house / auteur
        "Past Lives", "Portrait of a Lady on Fire", "Tár", "The Lighthouse",
        "Everything Everywhere All at Once", "Parasite", "Lady Bird",
        # Sci-fi / fantasy
        "Arrival", "Dune", "Interstellar", "Blade Runner 2049", "The Matrix",
        # Horror / thriller
        "Get Out", "Hereditary", "Knives Out",
        # Romance / heart
        "The Notebook", "Call Me by Your Name", "La La Land",
        # Classic
        "Casablanca", "Chinatown",
    ]
    tv_titles = [
        # Prestige drama
        "Breaking Bad", "The Sopranos", "The Wire", "Succession", "Mad Men",
        "Severance", "Better Call Saul",
        # Comfort sitcom
        "The Office", "Parks and Recreation", "Friends", "Seinfeld", "Schitt's Creek",
        "Abbott Elementary",
        # Dark comedy / prestige comedy
        "Fleabag", "Atlanta", "Barry", "The Bear", "Curb Your Enthusiasm",
        # Genre / fantasy / sci-fi
        "Game of Thrones", "Stranger Things", "The Mandalorian", "The Last of Us",
        "Black Mirror",
        # Reality / competition / unscripted
        "The Great British Bake Off", "Survivor", "RuPaul's Drag Race",
        # Crime / procedural
        "True Detective", "Mindhunter", "Only Murders in the Building",
        # International / art
        "Chernobyl", "Fleabag", "The Crown", "Squid Game",
        # Animation / kids-friendly
        "Bluey", "Arcane", "Avatar: The Last Airbender",
    ]
    book_titles = [
        # Literary fiction
        "The Great Gatsby", "To Kill a Mockingbird", "Beloved",
        "A Little Life", "Normal People", "Pachinko", "Demon Copperhead",
        # Page-turner thrillers / mysteries
        "Gone Girl", "The Silent Patient", "The Girl on the Train", "Before the Coffee Gets Cold",
        # Sci-fi / fantasy / speculative
        "Dune", "Project Hail Mary", "The Fifth Season", "Babel",
        "Fourth Wing", "A Court of Thorns and Roses",
        # Romance
        "The Seven Husbands of Evelyn Hugo", "Beach Read", "Red White and Royal Blue",
        # Nonfiction ideas
        "Sapiens", "Atomic Habits", "The Body Keeps the Score", "Thinking Fast and Slow",
        # Memoir / narrative nonfiction
        "Educated", "Crying in H Mart", "Becoming", "Just Kids",
        # Classic / literary canon
        "1984", "Pride and Prejudice", "Their Eyes Were Watching God",
        # YA / popular
        "The Hunger Games", "Harry Potter and the Sorcerer's Stone",
        # Contemporary literary-adjacent
        "Tomorrow and Tomorrow and Tomorrow", "Lessons in Chemistry",
    ]
    podcast_titles = [
        # True crime / narrative investigation
        "Serial", "Crime Junkie", "My Favorite Murder", "Scam Inc",
        # News / politics
        "The Daily", "The Ezra Klein Show", "Pod Save America",
        # Explainer / science
        "Radiolab", "Hidden Brain", "Freakonomics", "Huberman Lab", "99% Invisible",
        # Business / tech
        "How I Built This", "Hard Fork", "Planet Money", "Acquired",
        # Celebrity / comedy interview
        "Conan O'Brien Needs a Friend", "SmartLess", "Armchair Expert",
        "Office Ladies",
        # Storytelling / idea
        "This American Life", "Revisionist History", "Hardcore History",
        # Sports / pop culture
        "Pardon My Take", "The Rewatchables",
        # Culture / society
        "The Bill Simmons Podcast",
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

    # Reject study guides, summaries, and other derivative works that
    # masquerade as the original book in Open Library results.
    _JUNK_SUBSTRINGS = (
        "study guide", "studyguide", "summary of", "a summary",
        "cliffsnotes", "sparknotes", "shmoop", "quicklet",
        "analysis of", "workbook", "companion to", "notes on",
        "reader's guide", "teacher's guide",
    )

    def _is_real_book(result_title: str) -> bool:
        t = (result_title or "").lower()
        return not any(junk in t for junk in _JUNK_SUBSTRINGS)

    async def search_book_titles():
        results = []
        searches = await asyncio.gather(
            *[search_books(t) for t in book_titles], return_exceptions=True
        )
        for query, s in zip(book_titles, searches):
            if not isinstance(s, list) or not s:
                continue
            q_lower = query.lower().strip()
            # Pick the first result that (a) matches the title closely,
            # (b) has a cover image, and (c) isn't a study guide / summary.
            best = None
            for item in s[:10]:
                t_lower = (item.title or "").lower().strip()
                title_match = (
                    t_lower == q_lower
                    or t_lower.startswith(q_lower)
                    or q_lower.startswith(t_lower)
                )
                if title_match and item.image_url and _is_real_book(item.title):
                    best = item
                    break
            # Fallback: first result that at least isn't junk and has a cover
            if not best:
                for item in s[:10]:
                    if item.image_url and _is_real_book(item.title):
                        best = item
                        break
            if best:
                results.append(best)
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

    # Cap per category at enough items to fill ~3 rows on desktop (the
    # grid is 6-wide at lg). 18 gives three full rows, which matches the
    # "at least two more rows" ask and leaves room for duds that failed
    # to find a cover or good match in the external APIs.
    result = {
        "movie": [m.model_dump() for m in movies[:18]],
        "tv": [t.model_dump() for t in tv[:18]],
        "book": [b.model_dump() for b in books[:18]],
        "podcast": [p.model_dump() for p in podcasts[:18]],
    }
    # Store the UNFILTERED catalog. The response is filtered per-user
    # below so items they've already rated are removed.
    cache.set("quiz_items_base", result, ttl_seconds=86400)
    return _filter_quiz_items_for_user(result, db, user.id)


def _filter_quiz_items_for_user(base: dict, db: Session, user_id: int) -> dict:
    """Drop any items already in the user's profile or dismissed list.
    Used by /api/media/quiz-items so items the user rated via the
    this-or-that section above don't reappear in the curated grid."""
    known_normalized, _ = _build_known_titles(db, user_id)
    return {
        media_type: [item for item in items if not _is_known(item.get("title", ""), known_normalized)]
        for media_type, items in base.items()
    }


async def _enrich_quiz_items_via_tmdb(items: list[dict], media_type: str) -> list[dict]:
    """Enrich a list of quiz items with TMDB posters. Handles both
    movies (items use `year`) and TV shows (items use `tmdb_year` for
    the lookup + `years` for display). Shared between the movie and
    TV quiz endpoints so the enrichment rules stay consistent."""
    import asyncio

    from app.services.tmdb import search as tmdb_search

    async def enrich(item: dict) -> dict:
        try:
            results = await tmdb_search(item["title"], media_type)
        except Exception:
            results = []
        lookup_year = item.get("tmdb_year") if media_type == "tv" else item.get("year")
        best = None
        if results:
            # Prefer an exact year match since popular titles collide
            if lookup_year:
                for r in results[:10]:
                    if r.year == lookup_year:
                        best = r
                        break
            if not best:
                for r in results[:10]:
                    if r.image_url:
                        best = r
                        break
            if not best:
                best = results[0]
        return {
            "order": item["order"],
            "title": item["title"],
            "year": item.get("year") or item.get("years"),
            "weights": item["weights"],
            "media_type": media_type,
            # Carry the D2 pool tags through enrichment so the quiz-load
            # filter can match them against the user's onboarding picks.
            "generation": item.get("generation") or [],
            "scenes": item.get("scenes") or [],
            "image_url": best.image_url if best else None,
            "external_id": best.external_id if best else "",
            "source": best.source if best else "",
            "creator": best.creator if best else None,
            "description": best.description if best else None,
            "genres": best.genres if best else [],
        }

    enriched = await asyncio.gather(*[enrich(it) for it in items])
    return sorted(enriched, key=lambda x: x["order"])


@router.get("/taste-quiz/movies")
async def taste_quiz_movies_items(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Return the films for the movie taste quiz, enriched with TMDB
    metadata and filtered against the user's saved onboarding picks
    (generation + scenes). The full enriched pool is cached globally
    for 7 days so the TMDB lookups only run once — the per-user
    filter step is a cheap list comprehension applied on top of the
    cached pool."""
    from app import cache
    from app.services.movie_taste_quiz import FILMS, RESPONSE_OPTIONS, AXES, MIN_ANSWERED
    from app.services.taste_quiz_scoring import filter_quiz_items_by_onboarding, load_onboarding

    enriched = cache.get("movie_taste_quiz_items_enriched")
    if enriched is None:
        enriched = await _enrich_quiz_items_via_tmdb(FILMS, "movie")
        cache.set("movie_taste_quiz_items_enriched", enriched, ttl_seconds=86400 * 7)

    from app.services.taste_quiz_scoring import load_age_range
    age = load_age_range(db, user.id)

    # If age filtering will reduce the pool, let more items through the onboarding filter
    onboarding = load_onboarding(db, user.id)
    max_quiz = 50 if age in ("under_18", "over_50") else 25
    items = filter_quiz_items_by_onboarding(enriched, onboarding, max_items=max_quiz)

    if age == "under_18":
        # Block hard R / truly adult content
        _adult_movies = {"tropic thunder", "hereditary", "midsommar",
                         "the babadook", "gone girl", "zodiac", "prisoners",
                         "there will be blood", "no country for old men",
                         "marriage story", "decision to leave", "past lives"}
        items = [i for i in items
                 if i.get("title", "").lower() not in _adult_movies
                 and (i.get("year") or 0) >= 2005]
        # Interleave by genre/vibe so every type of teen hits something
        # diagnostic early. The goal is SIGNAL — different teens should
        # rate the first 8 items differently. Grouping by popularity
        # produces items everyone rates the same (no signal).
        _genre_buckets = {
            "comedy":    {"superbad", "bridesmaids", "21 jump street", "mean girls", "the proposal"},
            "family":    {"frozen", "coco", "ratatouille", "the super mario bros. movie", "sonic the hedgehog", "detective pikachu"},
            "action":    {"the dark knight", "top gun: maverick", "mission: impossible - fallout", "john wick", "creed", "mad max: fury road"},
            "horror":    {"it", "a quiet place", "nope", "get out", "five nights at freddy's"},
            "anime":     {"your name", "demon slayer: mugen train", "a silent voice"},
            "drama":     {"hidden figures", "the greatest showman", "bohemian rhapsody", "la la land", "the blind side", "soul surfer", "the martian"},
            "romcom":    {"crazy rich asians", "knives out", "the secret life of walter mitty"},
        }
        # Assign each item a genre bucket
        _title_to_genre = {}
        for genre, titles in _genre_buckets.items():
            for t in titles:
                _title_to_genre[t] = genre

        # Round-robin across genres so the quiz alternates
        from collections import defaultdict
        genre_queues = defaultdict(list)
        ungrouped = []
        for i in items:
            genre = _title_to_genre.get(i.get("title", "").lower())
            if genre:
                genre_queues[genre].append(i)
            else:
                ungrouped.append(i)

        # Interleave: pick one from each genre in rotation
        genre_order = ["comedy", "action", "family", "horror", "drama", "anime", "romcom"]
        interleaved = []
        round_num = 0
        while any(genre_queues[g] for g in genre_order) or ungrouped:
            for g in genre_order:
                if genre_queues[g]:
                    interleaved.append(genre_queues[g].pop(0))
            round_num += 1
            if round_num > 10:
                break
        interleaved.extend(ungrouped)
        items = interleaved
        log.info("movie_quiz [user=%d age=%s]: sorted %d items, first 5: %s",
                 user.id, age, len(items),
                 [i.get("title") for i in items[:5]])
    elif age == "18_35":
        # Newest first — this generation knows 2010s+ best
        items.sort(key=lambda i: -(i.get("year") or 0))
    elif age == "35_50":
        # Mix of eras — prioritize 1995-2015 sweet spot, then fan out
        def _score_35_50(i):
            y = i.get("year") or 2000
            if 1995 <= y <= 2015:
                return (0, -y)
            return (1, -y)
        items.sort(key=_score_35_50)
    elif age == "over_50":
        # Classics first — prioritize pre-2000, then chronological
        def _score_over_50(i):
            y = i.get("year") or 1990
            if y < 2000:
                return (0, y)  # oldest classics first
            return (1, -y)    # then newest of the modern stuff
        items.sort(key=_score_over_50)

    return {
        "items": items,
        "options": RESPONSE_OPTIONS,
        "axes": AXES,
        "min_answered": MIN_ANSWERED,
        "total_questions": len(items),
        "media_type": "movie",
        "media_label": "film",
        "media_label_plural": "films",
        "verb": "watched",
    }


@router.get("/taste-quiz/tv")
async def taste_quiz_tv_items(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Return the TV shows for the taste quiz, enriched with TMDB
    metadata and filtered against the user's saved onboarding picks
    (generation + scenes). Same caching + filter pattern as the
    movies endpoint: the enriched pool is cached globally, the
    per-user filter is applied at request time."""
    from app import cache
    from app.services.tv_taste_quiz import SHOWS, RESPONSE_OPTIONS, AXES, MIN_ANSWERED
    from app.services.taste_quiz_scoring import filter_quiz_items_by_onboarding, load_onboarding

    enriched = cache.get("tv_taste_quiz_items_enriched")
    if enriched is None:
        enriched = await _enrich_quiz_items_via_tmdb(SHOWS, "tv")
        cache.set("tv_taste_quiz_items_enriched", enriched, ttl_seconds=86400 * 7)

    from app.services.taste_quiz_scoring import load_age_range
    age = load_age_range(db, user.id)

    onboarding = load_onboarding(db, user.id)
    max_quiz = 50 if age in ("under_18", "over_50") else 25
    items = filter_quiz_items_by_onboarding(enriched, onboarding, max_items=max_quiz)

    # Helper to extract a numeric year from TV items (which may have "1994–2004" strings)
    def _tv_year(item):
        y = item.get("year")
        if isinstance(y, int):
            return y
        if isinstance(y, str) and y[:4].isdigit():
            return int(y[:4])
        return 2010  # default for items with no year data

    if age == "under_18":
        _adult_tv = {"game of thrones", "breaking bad", "euphoria", "the wire", "the sopranos",
                      "dexter", "true blood", "ozark", "narcos", "peaky blinders", "westworld",
                      "hannibal", "american horror story", "the walking dead", "sons of anarchy",
                      "boardwalk empire", "house of cards", "shameless", "nip/tuck", "sex and the city"}
        items = [i for i in items
                 if i.get("title", "").lower() not in _adult_tv
                 and _tv_year(i) >= 2005]
        # Teen-friendly shows first
        _teen_tv = {"stranger things", "the office", "friends", "schitt's creek",
                    "abbott elementary", "ted lasso", "wednesday", "heartstopper",
                    "never have i ever", "outer banks", "cobra kai", "bridgerton",
                    "the mandalorian", "loki", "wandavision", "the bear",
                    "yellowjackets", "only murders in the building", "parks and recreation",
                    "arrested development", "brooklyn nine-nine", "new girl",
                    "the good place", "modern family", "glee", "grey's anatomy"}
        items.sort(key=lambda i: (0 if i.get("title", "").lower() in _teen_tv else 1,
                                  -_tv_year(i)))
    elif age == "18_35":
        items.sort(key=lambda i: -_tv_year(i))
    elif age == "35_50":
        items.sort(key=lambda i: (0 if 1995 <= _tv_year(i) <= 2015 else 1, -_tv_year(i)))
    elif age == "over_50":
        items.sort(key=lambda i: (0 if _tv_year(i) < 2005 else 1, _tv_year(i) if _tv_year(i) < 2005 else -_tv_year(i)))

    result = {
        "items": items,
        "options": RESPONSE_OPTIONS,
        "axes": AXES,
        "min_answered": MIN_ANSWERED,
        "total_questions": len(items),
        "media_type": "tv",
        "media_label": "show",
        "media_label_plural": "shows",
        "verb": "watched",
    }
    return result


class QuizResponseItem(BaseModel):
    order: int
    value: int | None


class QuizSubmission(BaseModel):
    responses: list[QuizResponseItem]


@router.post("/taste-quiz/movies/score")
async def score_movie_quiz(
    submission: QuizSubmission,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Score the user's movie quiz responses and persist the result
    to UserPreferences so the recommendation prompts can blend it
    with the other quizzes."""
    from app.services.movie_taste_quiz import score_responses
    from app.services.taste_quiz_scoring import compute_next_quiz, persist_quiz_result

    result = score_responses([r.model_dump() for r in submission.responses])
    persist_quiz_result(db, user.id, "movies", result)
    if result.get("has_enough_data"):
        result["next_quiz"] = compute_next_quiz(db, user.id, current_slug="movies")
    log.info(
        "movie_taste_quiz [user=%d]: %d answered, top=%s",
        user.id,
        result.get("answered_count", 0),
        result["profiles"][0]["id"] if result.get("profiles") else "none",
    )
    return result


@router.post("/taste-quiz/tv/score")
async def score_tv_quiz(
    submission: QuizSubmission,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Score the user's TV quiz responses and persist."""
    from app.services.taste_quiz_scoring import compute_next_quiz, persist_quiz_result
    from app.services.tv_taste_quiz import score_responses

    result = score_responses([r.model_dump() for r in submission.responses])
    persist_quiz_result(db, user.id, "tv", result)
    if result.get("has_enough_data"):
        result["next_quiz"] = compute_next_quiz(db, user.id, current_slug="tv")
    log.info(
        "tv_taste_quiz [user=%d]: %d answered, top=%s",
        user.id,
        result.get("answered_count", 0),
        result["profiles"][0]["id"] if result.get("profiles") else "none",
    )
    return result


async def _enrich_books_via_open_library(items: list[dict]) -> list[dict]:
    """Enrich book items with cover images via unified search_books
    (OL primary, Google Books fallback)."""
    import asyncio

    from app.services.unified_search import search_books

    _JUNK = ("study guide", "summary of", "cliffsnotes", "sparknotes", "analysis of", "workbook", "companion to")

    async def enrich(item: dict) -> dict:
        query = f"{item['title']} {item.get('author', '')}".strip()
        t_lower = item["title"].lower().strip()
        try:
            results = await search_books(query)
        except Exception:
            results = []
        results = [r for r in results if not any(j in (r.title or "").lower() for j in _JUNK)]
        best = None
        for r in results[:10]:
            r_lower = (r.title or "").lower().strip()
            if (r_lower == t_lower or r_lower.startswith(t_lower) or t_lower.startswith(r_lower)) and r.image_url:
                best = r
                break
        if not best:
            for r in results[:10]:
                if r.image_url:
                    best = r
                    break
        if not best and results:
            best = results[0]
        return {
            "order": item["order"],
            "title": item["title"],
            "author": item.get("author"),
            "years": item.get("years"),
            "note_in_ui": item.get("note_in_ui"),
            "weights": item["weights"],
            "media_type": "book",
            # Phase D2 pool tags carried through for the quiz-load filter.
            "generation": item.get("generation") or [],
            "scenes": item.get("scenes") or [],
            "image_url": best.image_url if best else None,
            "external_id": best.external_id if best else "",
            "source": best.source if best else "",
            "creator": item.get("author"),  # ensure the UI shows the spec author
            "description": best.description if best else None,
            "genres": best.genres if best else [],
        }

    enriched = await asyncio.gather(*[enrich(it) for it in items])
    return sorted(enriched, key=lambda x: x["order"])


@router.get("/taste-quiz/books")
async def taste_quiz_books_items(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Return the two book quiz modules (fiction + nonfiction), each
    enriched with Open Library metadata and filtered against the
    user's saved onboarding. The enriched pools are cached globally
    for 7 days; the per-user filter is a cheap list comprehension
    applied on top."""
    import asyncio

    from app import cache
    from app.services.books_taste_quiz import (
        FICTION, NONFICTION, RESPONSE_OPTIONS, AXES,
        FICTION_MIN, NONFICTION_MIN,
    )
    from app.services.taste_quiz_scoring import filter_quiz_items_by_onboarding, load_onboarding

    fiction_enriched = cache.get("book_taste_quiz_items_fiction_enriched")
    nonfiction_enriched = cache.get("book_taste_quiz_items_nonfiction_enriched")
    if fiction_enriched is None or nonfiction_enriched is None:
        fiction_enriched, nonfiction_enriched = await asyncio.gather(
            _enrich_books_via_open_library(FICTION),
            _enrich_books_via_open_library(NONFICTION),
        )
        cache.set("book_taste_quiz_items_fiction_enriched", fiction_enriched, ttl_seconds=86400 * 7)
        cache.set("book_taste_quiz_items_nonfiction_enriched", nonfiction_enriched, ttl_seconds=86400 * 7)

    onboarding = load_onboarding(db, user.id)
    fiction_items = filter_quiz_items_by_onboarding(fiction_enriched, onboarding, min_items=10)
    nonfiction_items = filter_quiz_items_by_onboarding(nonfiction_enriched, onboarding, min_items=10)

    # Tag each item with its module so the frontend can split the
    # flow into Part 1 / Part 2 and the scoring endpoint knows which
    # module bucket each response belongs in.
    for it in fiction_items:
        it["module"] = "fiction"
    for it in nonfiction_items:
        it["module"] = "nonfiction"

    return {
        "modules": [
            {
                "id": "fiction",
                "label": "Part 1 · Fiction",
                "items": fiction_items,
                "min_answered": FICTION_MIN,
            },
            {
                "id": "nonfiction",
                "label": "Part 2 · Nonfiction",
                "items": nonfiction_items,
                "min_answered": NONFICTION_MIN,
            },
        ],
        "options": RESPONSE_OPTIONS,
        "axes": AXES,
        "media_type": "book",
        "media_label": "book",
        "media_label_plural": "books",
        "verb": "read",
        "total_questions": len(fiction_items) + len(nonfiction_items),
    }


class BookQuizResponseItem(BaseModel):
    module: str  # "fiction" | "nonfiction"
    order: int
    value: int | None


class BookQuizSubmission(BaseModel):
    responses: list[BookQuizResponseItem]


@router.get("/taste-quiz/books_fiction")
async def taste_quiz_books_fiction_items(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Fiction-only books quiz. Same shape as /taste-quiz/books but
    with only the fiction module, filtered against the user's saved
    onboarding picks so e.g. a gen_z + romance reader doesn't see
    Crime and Punishment next to Beach Read."""
    from app import cache
    from app.services.books_taste_quiz import FICTION, RESPONSE_OPTIONS, AXES, FICTION_MIN
    from app.services.taste_quiz_scoring import filter_quiz_items_by_onboarding, load_onboarding

    enriched = cache.get("book_taste_quiz_items_fiction_enriched")
    if enriched is None:
        enriched = await _enrich_books_via_open_library(FICTION)
        cache.set("book_taste_quiz_items_fiction_enriched", enriched, ttl_seconds=86400 * 7)

    onboarding = load_onboarding(db, user.id)
    fiction_items = filter_quiz_items_by_onboarding(enriched, onboarding, min_items=10)
    for it in fiction_items:
        it["module"] = "fiction"

    return {
        "modules": [
            {
                "id": "fiction",
                "label": "Fiction",
                "items": fiction_items,
                "min_answered": FICTION_MIN,
            },
        ],
        "options": RESPONSE_OPTIONS,
        "axes": AXES,
        "media_type": "book",
        "media_label": "book",
        "media_label_plural": "books",
        "verb": "read",
        "min_answered": FICTION_MIN,
        "total_questions": len(fiction_items),
    }


@router.get("/taste-quiz/books_nonfiction")
async def taste_quiz_books_nonfiction_items(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Nonfiction-only books quiz. Same pattern as books_fiction —
    the unblocker for nonfiction-only readers (memoir / history /
    true-crime fans) who don't want to wade through 20 novels first,
    now also filtered by onboarding scenes so a true-crime reader
    gets Say Nothing + In Cold Blood + Bad Blood up top."""
    from app import cache
    from app.services.books_taste_quiz import NONFICTION, RESPONSE_OPTIONS, AXES, NONFICTION_MIN
    from app.services.taste_quiz_scoring import filter_quiz_items_by_onboarding, load_onboarding

    enriched = cache.get("book_taste_quiz_items_nonfiction_enriched")
    if enriched is None:
        enriched = await _enrich_books_via_open_library(NONFICTION)
        cache.set("book_taste_quiz_items_nonfiction_enriched", enriched, ttl_seconds=86400 * 7)

    onboarding = load_onboarding(db, user.id)
    nonfiction_items = filter_quiz_items_by_onboarding(enriched, onboarding, min_items=10)
    for it in nonfiction_items:
        it["module"] = "nonfiction"

    return {
        "modules": [
            {
                "id": "nonfiction",
                "label": "Nonfiction",
                "items": nonfiction_items,
                "min_answered": NONFICTION_MIN,
            },
        ],
        "options": RESPONSE_OPTIONS,
        "axes": AXES,
        "media_type": "book",
        "media_label": "book",
        "media_label_plural": "books",
        "verb": "read",
        "min_answered": NONFICTION_MIN,
        "total_questions": len(nonfiction_items),
    }


@router.get("/taste-quiz/podcast-bonus")
async def taste_quiz_podcast_bonus(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Generate 4 podcast recommendations BLENDED from every completed
    taste quiz. Fired only on the all-quizzes-done celebration screen.

    Why no podcast quiz: the podcast landscape is too fragmented and
    niche for a universal 20-item lineup. Instead, once the user has
    given us taste direction on film, TV, and books, we translate the
    combined axes into 4 curated podcast picks they can rate or skip.

    Reads every saved quiz result, builds a combined prompt with the
    top profiles + aggregated axis deltas across all media, asks
    Gemini for 4 podcast picks with concrete reasons, and enriches
    each via iTunes search. Cached 24h per user."""
    from app import cache
    from app.config import settings
    from app.services.itunes import search as search_podcasts
    from app.services.taste_quiz_scoring import load_quiz_results

    cache_key = f"podcast_bonus:{user.id}:all"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    quiz_results = load_quiz_results(db, user.id)
    if not quiz_results:
        return {"items": []}

    # Collect profile leans + top axes from every completed quiz so
    # the AI has a full picture of the user's cross-medium direction.
    medium_labels = {"movies": "Film", "tv": "TV", "books": "Books"}
    medium_lines: list[str] = []
    for slug in ("movies", "tv", "books"):
        q = quiz_results.get(slug)
        if not q or not q.get("profiles"):
            continue
        profiles = q.get("profiles") or []
        lean = " / ".join(p.get("name", "") for p in profiles[:2] if p.get("name"))
        scores = q.get("axis_scores") or {}
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        high = [k for k, v in ranked if v > 0][:3]
        low = [k for k, v in ranked if v < 0][-2:]
        high_str = ", ".join(high) or "—"
        low_str = ", ".join(low) or "—"
        medium_lines.append(
            f"- **{medium_labels[slug]}**: {lean} (high: {high_str}; low: {low_str})"
        )

    if not medium_lines:
        return {"items": []}

    if not settings.gemini_api_key:
        return {"items": []}

    known_normalized, _ = _build_known_titles(db, user.id)

    try:
        from app.services.gemini import generate

        blended_block = "\n".join(medium_lines)

        prompt = f"""You are a podcast curator. A user has just finished every NextUp taste quiz across film, TV, and books. Based on their full cross-medium direction, pick 4 podcasts they'd likely enjoy.

THEIR FULL TASTE DIRECTION:
{blended_block}

TASK: Pick 4 podcasts that match the BLEND of signals above — not just one medium. Translate axes into podcast equivalents:
- High darkness / moral ambiguity → true crime, investigative journalism, dark narrative
- High ideas → explainer / science / long-form interview podcasts
- High pace tolerance / commitment / serialization → long-form narrative series (Serial, Scam Inc, Revisionist History style)
- High irony / comedy → comedy interview, absurdist chat shows
- High emotional → personal narrative, storytelling podcasts
- High ambiguity → philosophy, science-of-the-mind, speculative
- Low emotional + high irony → dry wit interview podcasts
- Prestige-drama TV fans → investigative narrative podcasts that work like long-form audio prestige drama
- Literary-fiction readers → book-focused podcasts, author interviews, essayistic shows

Rules:
- NO mainstream defaults unless they actually match the axes. Don't reflexively pick The Daily or Joe Rogan.
- Variety: don't pick 4 of one type. Span different podcast styles.
- Each pick needs a reason that cites at least one SPECIFIC axis or profile from the blend above.
- The best picks hit MULTIPLE signals across media at once — say so explicitly when they do.
- Do NOT pick anything the user already has in their library.
- Already-owned titles to avoid: {', '.join(list(known_normalized)[:40]) if known_normalized else 'none'}

Return ONLY valid JSON, no markdown:
[
  {{"title": "...", "reason": "Short concrete reason citing the axis or profile match"}},
  {{"title": "...", "reason": "..."}},
  {{"title": "...", "reason": "..."}},
  {{"title": "...", "reason": "..."}}
]"""

        text = (await generate(prompt)).strip()
        parsed = _parse_ai_json(text, "podcast_bonus:all")
        if not isinstance(parsed, list):
            return {"items": []}

        # Enrich each with iTunes search for poster + external_id
        import asyncio

        async def enrich(pick: dict) -> dict | None:
            title = pick.get("title", "")
            if not title:
                return None
            if _is_known(title, known_normalized):
                return None
            try:
                matches = await search_podcasts(title)
            except Exception:
                matches = []
            matches = _rank_by_title_match(title, matches)
            if not matches:
                return {
                    "title": title,
                    "year": None,
                    "creator": None,
                    "image_url": None,
                    "external_id": "",
                    "source": "",
                    "media_type": "podcast",
                    "reason": pick.get("reason", ""),
                }
            best = matches[0]
            if _is_known(best.title, known_normalized):
                return None
            return {
                "title": best.title,
                "year": best.year,
                "creator": best.creator,
                "image_url": best.image_url,
                "external_id": best.external_id,
                "source": best.source,
                "media_type": "podcast",
                "reason": pick.get("reason", ""),
            }

        enriched_list = await asyncio.gather(*[enrich(p) for p in parsed[:6]])
        items = [it for it in enriched_list if it is not None][:4]
        result = {"items": items}
        log.info(
            "podcast_bonus [user=%d]: %d picks surfaced (blended across all quizzes)",
            user.id, len(items),
        )
        cache.set(cache_key, result, ttl_seconds=86400)  # 24h
        return result
    except Exception as e:
        log.exception("podcast_bonus failed: %s", str(e))
        return {"items": []}


@router.post("/taste-quiz/books/score")
async def score_book_quiz(
    submission: BookQuizSubmission,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Score the two-module book quiz. Returns fiction/nonfiction
    per-module counts, a combined axis vector, profile matches, and
    which module drove the result."""
    from app.services.books_taste_quiz import score_book_responses
    from app.services.taste_quiz_scoring import compute_next_quiz, persist_quiz_result

    result = score_book_responses([r.model_dump() for r in submission.responses])
    persist_quiz_result(db, user.id, "books", result)
    if result.get("has_enough_data"):
        result["next_quiz"] = compute_next_quiz(db, user.id, current_slug="books")
    log.info(
        "book_taste_quiz [user=%d]: fic=%d non=%d top=%s dom=%s",
        user.id,
        result.get("fiction_answered", 0),
        result.get("nonfiction_answered", 0),
        result["profiles"][0]["id"] if result.get("profiles") else "none",
        result.get("dominant_module"),
    )
    return result


@router.post("/taste-quiz/books_fiction/score")
async def score_book_quiz_fiction(
    submission: BookQuizSubmission,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Score the fiction-only books quiz. Routes through the same
    score_book_responses function as the combined endpoint, which
    handles a fiction-only payload by falling back to fiction-only
    profile matching. Persisted under the 'books' slug so the rest
    of the app (taste DNA page, recommendation prompts) sees a books
    profile regardless of whether the user took the combined quiz
    or just one module."""
    from app.services.books_taste_quiz import score_book_responses
    from app.services.taste_quiz_scoring import compute_next_quiz, persist_quiz_result

    result = score_book_responses([r.model_dump() for r in submission.responses])
    persist_quiz_result(db, user.id, "books", result)
    if result.get("has_enough_data"):
        result["next_quiz"] = compute_next_quiz(db, user.id, current_slug="books")
    log.info(
        "book_taste_quiz_fiction [user=%d]: fic=%d top=%s",
        user.id,
        result.get("fiction_answered", 0),
        result["profiles"][0]["id"] if result.get("profiles") else "none",
    )
    return result


@router.post("/taste-quiz/books_nonfiction/score")
async def score_book_quiz_nonfiction(
    submission: BookQuizSubmission,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Score the nonfiction-only books quiz. Same path as the fiction
    split — score_book_responses sees only nonfiction responses and
    uses nonfiction-only profile matching. Persisted under 'books'."""
    from app.services.books_taste_quiz import score_book_responses
    from app.services.taste_quiz_scoring import compute_next_quiz, persist_quiz_result

    result = score_book_responses([r.model_dump() for r in submission.responses])
    persist_quiz_result(db, user.id, "books", result)
    if result.get("has_enough_data"):
        result["next_quiz"] = compute_next_quiz(db, user.id, current_slug="books")
    log.info(
        "book_taste_quiz_nonfiction [user=%d]: non=%d top=%s",
        user.id,
        result.get("nonfiction_answered", 0),
        result["profiles"][0]["id"] if result.get("profiles") else "none",
    )
    return result


class OnboardingSubmission(BaseModel):
    media_types: list[str] = []
    generation: str = "mix"
    scenes: list[str] = []
    streaming_services: list[int] = []
    media_regions: list[str] = []
    age_range: str = ""


@router.post("/onboarding")
async def save_onboarding_answers(
    submission: OnboardingSubmission,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Persist the 4-step onboarding wizard answers. The quiz item
    pools (Phase D2) read these to filter quiz items down to the
    user's generation + scenes intersection. The recommendation
    prompts (Phase E) read them as additional taste anchors.

    Returns the cleaned answers + a suggested next URL based on the
    user's media-type picks (first selected quiz, or /quick-start as
    a fallback)."""
    from app.services.taste_quiz_scoring import save_onboarding

    cleaned = save_onboarding(db, user.id, submission.model_dump())

    # Pick the first quiz the user should take based on their media
    # mix. Order: movie -> tv -> fiction -> nonfiction. Podcasts have
    # no standalone quiz (they ship as a bonus after the others).
    next_url = "/quick-start"
    media_to_url = [
        ("movie", "/quick-start/movies"),
        ("tv", "/quick-start/tv"),
        ("book_fiction", "/quick-start/books/fiction"),
        ("book_nonfiction", "/quick-start/books/nonfiction"),
    ]
    for mt, url in media_to_url:
        if mt in cleaned["media_types"]:
            next_url = url
            break

    log.info(
        "onboarding_saved [user=%d]: types=%s gen=%s scenes=%s -> %s",
        user.id,
        cleaned["media_types"],
        cleaned["generation"],
        cleaned["scenes"],
        next_url,
    )
    return {"saved": cleaned, "next_url": next_url}


@router.post("/streaming-services")
async def update_streaming_services(
    payload: dict,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Update just the user's streaming services without touching other onboarding data."""
    import json
    from app.models import UserPreferences

    services = payload.get("streaming_services", [])
    VALID = {8, 9, 15, 21, 38, 103, 337, 350, 380, 385, 386, 531, 1899}
    cleaned = [int(s) for s in services if int(s) in VALID]

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)

    try:
        existing = json.loads(prefs.quiz_results) if prefs.quiz_results else {}
    except (json.JSONDecodeError, TypeError):
        existing = {}

    onboarding = existing.get("onboarding", {})
    onboarding["streaming_services"] = cleaned
    existing["onboarding"] = onboarding
    prefs.quiz_results = json.dumps(existing)
    db.commit()

    return {"streaming_services": cleaned}


@router.get("/taste-test")
async def taste_test():
    """Return contrasting taste-axis pools. Each axis has two LABELED
    SIDES, and each side contains 3 items so the user can pick one
    they've actually seen/read/heard rather than being forced to judge
    a single item they might not know.

    The user taps any items they've genuinely consumed and rates them
    inline — each rated item flows into the profile as a real taste
    signal. Items left untapped are skipped.

    The goal is to probe real taste dimensions without requiring the
    user to have seen one specific title."""
    import asyncio

    from app import cache
    from app.services.tmdb import search as tmdb_search
    from app.services.unified_search import search_books
    from app.services.itunes import search as search_podcasts

    cached = cache.get("taste_test")
    if cached is not None:
        return cached

    # Each axis probes one taste dimension. Format:
    #   (axis_label, left_label, right_label, [left items], [right items])
    # Items are (title, media_type) for movies/tv/podcasts, or
    # (title, media_type, author) for books — author helps us nail the
    # right Open Library record instead of grabbing a random edition
    # or study guide.
    AXES: list[tuple[str, str, str, list[tuple], list[tuple]]] = [
        (
            "Spectacle or intimacy?",
            "Spectacle",
            "Intimacy",
            [("Avengers: Endgame", "movie"), ("Top Gun: Maverick", "movie"), ("Oppenheimer", "movie")],
            [("Past Lives", "movie"), ("The Holdovers", "movie"), ("Aftersun", "movie")],
        ),
        (
            "Silly or serious?",
            "Silly",
            "Serious",
            [("Step Brothers", "movie"), ("Anchorman", "movie"), ("Superbad", "movie")],
            [("Manchester by the Sea", "movie"), ("Moonlight", "movie"), ("There Will Be Blood", "movie")],
        ),
        (
            "Prestige drama or comfort sitcom?",
            "Prestige drama",
            "Comfort sitcom",
            [("Succession", "tv"), ("Mad Men", "tv"), ("Better Call Saul", "tv")],
            [("The Office", "tv"), ("Parks and Recreation", "tv"), ("Schitt's Creek", "tv")],
        ),
        (
            "Plot-driven or vibes-driven?",
            "Plot-driven",
            "Vibes-driven",
            [("Knives Out", "movie"), ("Gone Girl", "movie"), ("The Prestige", "movie")],
            [("Lost in Translation", "movie"), ("Call Me by Your Name", "movie"), ("Before Sunrise", "movie")],
        ),
        (
            "Page-turner thriller or literary slow-burn?",
            "Page-turner",
            "Slow-burn",
            [
                ("Gone Girl", "book", "Gillian Flynn"),
                ("The Silent Patient", "book", "Alex Michaelides"),
                ("The Girl on the Train", "book", "Paula Hawkins"),
            ],
            [
                ("A Little Life", "book", "Hanya Yanagihara"),
                ("Normal People", "book", "Sally Rooney"),
                ("Pachinko", "book", "Min Jin Lee"),
            ],
        ),
        (
            "Fantasy escapism or contemporary realism?",
            "Fantasy",
            "Contemporary",
            [
                ("Dune", "book", "Frank Herbert"),
                ("Fourth Wing", "book", "Rebecca Yarros"),
                ("A Court of Thorns and Roses", "book", "Sarah J. Maas"),
            ],
            [
                ("Normal People", "book", "Sally Rooney"),
                ("Lessons in Chemistry", "book", "Bonnie Garmus"),
                ("Tomorrow, and Tomorrow, and Tomorrow", "book", "Gabrielle Zevin"),
            ],
        ),
        (
            "Nonfiction ideas or narrative fiction?",
            "Nonfiction",
            "Narrative fiction",
            [
                ("Sapiens", "book", "Yuval Noah Harari"),
                ("Atomic Habits", "book", "James Clear"),
                ("Thinking, Fast and Slow", "book", "Daniel Kahneman"),
            ],
            [
                ("Pachinko", "book", "Min Jin Lee"),
                ("The Kite Runner", "book", "Khaled Hosseini"),
                ("Demon Copperhead", "book", "Barbara Kingsolver"),
            ],
        ),
        (
            "True crime or explainer?",
            "True crime",
            "Explainer",
            [("Serial", "podcast"), ("Crime Junkie", "podcast"), ("My Favorite Murder", "podcast")],
            [("Radiolab", "podcast"), ("Hidden Brain", "podcast"), ("Freakonomics", "podcast")],
        ),
    ]

    _BOOK_JUNK_SUBSTRINGS = (
        "study guide", "studyguide", "summary of", "a summary",
        "cliffsnotes", "sparknotes", "shmoop", "quicklet",
        "analysis of", "workbook", "companion to", "notes on",
    )

    def _is_real_book_title(t: str) -> bool:
        tl = (t or "").lower()
        return not any(j in tl for j in _BOOK_JUNK_SUBSTRINGS)

    async def fetch_one(*args) -> dict | None:
        # Accept (title, media_type) or (title, media_type, author).
        title = args[0]
        media_type = args[1]
        author = args[2] if len(args) >= 3 else None
        try:
            if media_type in ("movie", "tv"):
                results = await tmdb_search(title, media_type)
            elif media_type == "book":
                # For books, include the author in the query so Open
                # Library returns the right work instead of a random
                # edition, study guide, or unrelated book.
                query = f"{title} {author}" if author else title
                results = await search_books(query)
            elif media_type == "podcast":
                results = await search_podcasts(title)
            else:
                return None
        except Exception as e:
            log.info("taste_test fetch_one failed for %s: %s", title, str(e))
            return None
        if not results:
            log.info("taste_test fetch_one: no results for %s (%s)", title, media_type)
            return None

        # For books, pre-filter out study guides / companions.
        if media_type == "book":
            results = [r for r in results if _is_real_book_title(r.title)]
            if not results:
                log.info("taste_test fetch_one: no real-book results for %s", title)
                return None

        t_lower = title.lower().strip()
        best = None
        # 1) Exact / startswith title match with image
        for item in results[:10]:
            it_lower = (item.title or "").lower().strip()
            if (it_lower == t_lower or it_lower.startswith(t_lower) or t_lower.startswith(it_lower)) and item.image_url:
                best = item
                break
        if not best:
            # 2) Any result with an image
            for item in results[:10]:
                if item.image_url:
                    best = item
                    break
        if not best:
            best = results[0]
        return best.model_dump()

    # Flatten every item (can be 2-tuple or 3-tuple) and fetch in
    # parallel, then reassemble per axis.
    flat_requests: list[tuple] = []
    for _, _, _, left, right in AXES:
        flat_requests.extend(left)
        flat_requests.extend(right)
    resolved = await asyncio.gather(*[fetch_one(*entry) for entry in flat_requests])

    axes_out = []
    idx = 0
    for axis_label, left_label, right_label, left, right in AXES:
        left_items = [r for r in resolved[idx : idx + len(left)] if r]
        idx += len(left)
        right_items = [r for r in resolved[idx : idx + len(right)] if r]
        idx += len(right)
        # Drop the axis entirely if either side came back empty.
        if left_items and right_items:
            axes_out.append(
                {
                    "axis": axis_label,
                    "left": {"label": left_label, "items": left_items},
                    "right": {"label": right_label, "items": right_items},
                }
            )

    result = {"axes": axes_out}
    cache.set("taste_test", result, ttl_seconds=86400 * 7)  # 7 days, content is static
    return result


@router.post("/refresh-recommendations")
async def refresh_recommendations(user: User = Depends(require_user)):
    """Explicitly clear recommendation caches so they regenerate on next load."""
    from fastapi import HTTPException

    from app import cache
    from app.config import settings

    if not settings.admin_email or user.email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=403, detail="Admin only")

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
        if e.rating and e.rating >= 3:
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
            item_lines = [f"  - {e.title} — {e.rating}/5 [{e.genres or ''}]" for e in items]
            lines.append(f"{label}:\n" + "\n".join(item_lines))
    profile_summary = "\n\n".join(lines)

    recent_summary = ""
    if recent:
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/5)" for e in recent[:8]]
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
        result = _parse_ai_json(text, "insights")
        if not isinstance(result, dict):
            return {"insights": []}
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
    """Generate an AI analysis of the user's taste across all media types.
    Cached for up to 30 days; regeneration is debounced — we only spend
    a fresh Gemini call if the profile has grown by ≥10 items OR ≥7 days
    have passed since the last analysis. The answer for a 300-book
    profile doesn't meaningfully change after one new book, and this
    saves the largest single prompt in the app from firing every time
    the user rates something."""
    import json
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import DismissedItem, MediaEntry

    cache_key = f"taste_dna:{user.id}"
    if refresh:
        cache.invalidate(cache_key)

    # Pull ALL entries — unrated items (esp. from bulk imports) are still a signal:
    # the user deliberately added/shelved them.
    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    current_entry_count = len(entries)

    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            meta = cached.get("_meta") if isinstance(cached, dict) else None
            if meta:
                cached_count = meta.get("entry_count", 0)
                generated_at = meta.get("generated_at", 0)
                age_days = (datetime.utcnow().timestamp() - generated_at) / 86400
                # Debounce: a handful of new items or a few days of no
                # activity don't meaningfully change the DNA.
                if current_entry_count - cached_count < 10 and age_days < 7:
                    return cached
            else:
                # Legacy cached result without metadata — return as-is.
                return cached

    if not settings.gemini_api_key:
        return {"themes": [], "summary": "", "by_medium": {}, "signature_items": [], "avoided": "", "recent_shift": ""}

    if current_entry_count < 3:
        return {"themes": [], "summary": "Add at least a few items to see your taste DNA.", "by_medium": {}, "signature_items": [], "avoided": "", "recent_shift": ""}

    # Partition: loved (rated 4-5), liked (3), consumed-unrated, queued (want_to_consume), low-rated
    loved = sorted([e for e in entries if e.rating and e.rating >= 4], key=lambda e: e.rating or 0, reverse=True)
    liked = sorted([e for e in entries if e.rating and e.rating == 3], key=lambda e: e.rating or 0, reverse=True)
    consumed_unrated = [e for e in entries if e.status == "consumed" and not e.rating]
    queued = [e for e in entries if e.status == "want_to_consume"]
    low_rated = sorted([e for e in entries if e.rating and e.rating <= 2], key=lambda e: e.rating or 0)[:10]

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
            block.append("  Loved (4-5/5):")
            for e in _sample(mt_loved, 10):
                block.append(f"    - {e.title} ({e.year or '?'}) — {e.rating}/5 [{e.genres or ''}]")
        if mt_liked:
            block.append("  Liked (3/5):")
            for e in _sample(mt_liked, 6):
                block.append(f"    - {e.title} ({e.year or '?'}) — {e.rating}/5 [{e.genres or ''}]")
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
            rating_str = f", {e.rating}/5" if e.rating else ""
            recent_lines.append(f"  - {e.title} ({e.media_type}{rating_str})")
        recent_summary = "\n\nRECENT MOOD (last 30 days, rated or added):\n" + "\n".join(recent_lines)

    avoided_summary = ""
    if low_rated or dismissed:
        avoided_lines = [f"  - {e.title} ({e.media_type}) — rated {e.rating}/5" for e in low_rated[:6]]
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
- "Loved (4-5/5)" items are the strongest signal of taste — weight these heaviest.
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
        # Debounce metadata: entry count and generation timestamp. The
        # endpoint reads these on subsequent hits and skips regeneration
        # if the profile hasn't drifted much.
        result["_meta"] = {
            "entry_count": current_entry_count,
            "generated_at": datetime.utcnow().timestamp(),
        }
        # 30 day TTL — the debounce gate is what controls freshness,
        # not the cache TTL. Cache only expires as a last-resort safety.
        cache.set(cache_key, result, ttl_seconds=2592000)
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
    known_normalized, known_display = _build_known_titles(db, user.id)

    # Build cross-medium taste summary
    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_items = []
    for e in entries:
        if e.rating and e.rating >= 4:
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
            lines = [f"  - {e.title} — {e.rating}/5" for e in items]
            taste_sections.append(f"{label}:\n" + "\n".join(lines))

    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    recent_text = ""
    if recent_items:
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/5)" for e in recent_items[:6]]
        recent_text = f"\n\nRECENTLY RATED (last 30 days):\n" + "\n".join(recent_lines)

    # Pack as many known titles into the prompt as will fit in ~6000 chars.
    avoid_titles: list[str] = []
    char_budget = 6000
    for t in known_display:
        if char_budget <= 0:
            break
        avoid_titles.append(t)
        char_budget -= len(t) + 2
    avoid_str = ", ".join(avoid_titles) if avoid_titles else "none"

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
        from app.services.taste_quiz_scoring import build_quiz_signals_block
        quiz_signals = build_quiz_signals_block(db, user.id)

        mood_line = f"\nCURRENT MOOD: {req.mood}" if req.mood else ""
        prompt = f"""You are NextUp, a cross-medium taste expert. Pick ONE perfect thing — fiction or nonfiction — for this person to consume right now based on their taste, available time, and mood.

{quiz_signals}
USER'S TASTE PROFILE:
{taste_summary}
{recent_text}

CONTEXT:
- Available time: {req.available_time}
- Time-appropriate media: {time_hint}{mood_line}

NONFICTION IS WELCOME: documentaries, memoirs, idea books, interview/explainer podcasts, narrative nonfiction — all valid. Match the user's fiction/nonfiction balance.

REASON FORMAT: Each "reason" MUST have TWO parts: (1) What it is — a 1-sentence premise so the user knows what they're looking at. (2) Why they'll like it — cite a specific item from their profile and name a concrete connection (theme, tone, idea). Never match on surface features.

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
        pick = _parse_ai_json(text, "tonight")
        if not isinstance(pick, dict):
            raise HTTPException(status_code=503, detail="Couldn't read AI response; try again.")

        if _is_known(pick.get("title", ""), known_normalized):
            log.info("tonight: dropping AI pick '%s' — already in library", pick.get("title"))
            raise HTTPException(status_code=503, detail="AI suggested an item you already have; try again.")

        # Enrich with poster
        matches = await unified_search(pick.get("title", ""), pick.get("media_type"))
        matches = _rank_by_title_match(pick.get("title", ""), matches)
        if matches and not _is_known(matches[0].title, known_normalized):
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


@router.get("/home-bundle")
async def home_bundle(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """One-shot endpoint that builds the profile context ONCE and asks
    Gemini for top picks + missing-type suggestions + insights in a
    single round-trip. Replaces three separate calls that each resent
    the same taste summary. Cut home-page Gemini cost by roughly half."""
    import asyncio
    import json
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import MediaEntry
    from app.services.unified_search import unified_search

    cache_key = f"home_bundle:{user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    empty_bundle = {"top_picks": [], "suggestions": {}, "themes": {}, "insights": []}
    if not settings.gemini_api_key:
        return empty_bundle

    consumed = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.status == "consumed"
    ).all()
    want = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume"
    ).all()
    known_normalized, known_display = _build_known_titles(db, user.id)

    if not consumed:
        return empty_bundle

    # Figure out which types are missing from the queue — only ask the AI
    # for suggestions in those categories.
    queue_types = {item.media_type for item in want}
    all_types = {"movie", "tv", "book", "podcast"}
    missing_types = all_types - queue_types

    # Build the shared taste summary ONCE — this is the big token cost
    # we're de-duplicating. Loved items per type + recent mood.
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    recent_items = []
    for e in consumed:
        if e.rating and e.rating >= 4:
            by_type.setdefault(e.media_type, []).append(e)
        if e.rated_at and e.rated_at >= thirty_days_ago and e.rating:
            recent_items.append(e)

    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    taste_sections = []
    label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    for mt, label in label_map.items():
        items = by_type.get(mt, [])[:8]
        if items:
            lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/5 [{e.genres or ''}]" for e in items]
            taste_sections.append(f"{label}:\n" + "\n".join(lines))
    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    # Determine profile maturity based on age, not just item count.
    # A profile is "settled" after ~14 days — before that, the user is
    # still remembering and adding things, so recency is data-entry
    # order, not genuine mood signal.
    from datetime import timedelta
    profile_age_days = 0
    oldest_entry = (
        db.query(MediaEntry.created_at)
        .filter(MediaEntry.user_id == user.id)
        .order_by(MediaEntry.created_at.asc())
        .first()
    )
    if oldest_entry and oldest_entry.created_at:
        profile_age_days = (datetime.utcnow() - oldest_entry.created_at).days

    recent_section = ""
    profile_settled = profile_age_days >= 14
    if recent_items and profile_settled:
        # Settled profile: recent ratings reflect genuine current mood
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/5)" for e in recent_items[:10]]
        recent_section = "\n\nRECENT MOOD (last 30 days — what they're gravitating toward right now):\n" + "\n".join(recent_lines)
    elif recent_items:
        # New profile (under 14 days old): user is still building,
        # recency reflects data-entry order, not taste direction
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/5)" for e in recent_items[:5]]
        recent_section = "\n\nRECENTLY ADDED (this profile is less than 2 weeks old — the user is still building their library. These items reflect data entry order, NOT current mood or preference. Weight the FULL taste profile above equally across all items. Do not over-index on the last few things added):\n" + "\n".join(recent_lines)

    # Age range context for the AI
    from app.services.taste_quiz_scoring import load_age_range
    bundle_age = load_age_range(db, user.id)
    age_context = ""
    if bundle_age == "under_18":
        age_context = "\nAGE: Under 18. Only PG/PG-13 content. No R-rated, no explicit themes. Focus on 2010-present across all media types."
    elif bundle_age == "35_50":
        age_context = "\nAGE: 35-50. Include titles from the 90s-2020s across movies, TV, books, and podcasts."
    elif bundle_age == "over_50":
        age_context = "\nAGE: Over 50. Include classics alongside newer content. Respect their depth of experience."

    # Avoid list — pack as many titles as fit in the budget.
    avoid_titles: list[str] = []
    char_budget = 6000
    for t in known_display:
        if char_budget <= 0:
            break
        avoid_titles.append(t)
        char_budget -= len(t) + 2
    avoid_str = ", ".join(avoid_titles) if avoid_titles else "none"

    missing_types_list = sorted(missing_types) if missing_types else []

    try:
        from app.services.gemini import generate

        suggestions_schema = ""
        if missing_types_list:
            suggestions_schema = (
                "  \"suggestions\": {\n"
                + ",\n".join(
                    f'    "{mt}": [{{"title": "...", "creator": "...", "year": 2020, "reason": "What it is + why", "predicted_rating": 4.5}}, ... 5 items]'
                    for mt in missing_types_list
                )
                + "\n  },"
            )
        else:
            suggestions_schema = '  "suggestions": {},'

        from app.services.taste_quiz_scoring import build_quiz_signals_block, load_streaming_services
        from app.services.tmdb import TIER1_PROVIDERS
        quiz_signals = build_quiz_signals_block(db, user.id)
        resonance_signals = build_resonance_block(db, user.id)
        rec_feedback = build_rec_feedback_block(db, user.id)
        user_services = load_streaming_services(db, user.id)
        if user_services:
            service_names = [TIER1_PROVIDERS.get(pid, f"Service {pid}") for pid in user_services]
            streaming_context = f"\nSTREAMING SERVICES: The user subscribes to: {', '.join(service_names)}. Strongly prefer items available on these services. Most picks should be watchable tonight. If recommending something on a service they don't have, explicitly note it's available to rent/buy."
        else:
            streaming_context = ""

        # Six life-context themes — each resolves to a specific mode of
        # consumption the user might actually be in. These replace the
        # old "Patterns in your taste" insights block on the home page.
        theme_catalog = [
            ("walking_the_dog", "Something to listen to while walking the dog, cooking, cleaning the house, or running errands", "podcast", "podcast: 30-60 min, conversational or narrative, one you can drop in and out of without losing the thread"),
            ("tonight_binge",    "Tonight's binge",                                                                                "tv",      "tv: 1-2 hour episodes, propulsive, something the user will be eager to engage with and that feels well aligned with their taste"),
            ("wind_down",        "Wind down before bed",                                                                           "book",    "book or slow tv: low stakes, light and entertaining, cozy. MIX familiar comfort picks from the user's library (things they've already watched/read and would happily revisit) with new suggestions they haven't tried. Aim for roughly half familiar, half new."),
            ("background_work",  "Background while you work",                                                                      "podcast", "podcast or comfort tv: familiar or conversational, doesn't demand attention but rewards it when you lean in. MIX comfort rewatches from the user's library (shows they know and love) with new suggestions. Aim for roughly half familiar, half new."),
            ("weekend_binge",    "Weekend binge",                                                                                  "any",     "movie, tv limited series, OR book (any length). This category can ask more of the user than the weeknight binge — engaging, something worth sitting with on a Saturday. Mix the media types across the 4 picks — don't return all one category."),
            ("quick_escape",     "Quick escape",                                                                                   "movie",   "movie or short-form tv: 15-90 min, fun, the thing you'd watch when you have a pocket of time and need out of your own head, a laugh, or to feel inspired or positive"),
        ]
        theme_schema_lines = [
            f'    "{slug}": [{{"title": "...", "creator": "...", "media_type": "movie|tv|book|podcast", "year": 2020, "reason": "What it is + why", "predicted_rating": 4.5}}, ... 8 items]'
            for (slug, _label, _primary, _guide) in theme_catalog
        ]
        theme_schema = "  \"themes\": {\n" + ",\n".join(theme_schema_lines) + "\n  },"
        theme_guide = "\n".join(
            f"  - {slug} ({label}) — {guide}"
            for (slug, label, _primary, guide) in theme_catalog
        )

        prompt = f"""You are a cross-medium taste expert. Find connections between books, TV, movies, and podcasts — fiction AND nonfiction — that share themes, ideas, tone, subject matter, or emotional register.

{quiz_signals}
{resonance_signals}
{rec_feedback}
USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}
{streaming_context}{age_context}

THIN PROFILE GUIDANCE:
If the user has fewer than 15 rated items, you have limited signal. In this case:
- Stick to WIDELY acclaimed, well-known titles that broadly match the genres and tones visible in their profile. Do NOT recommend obscure or niche items.
- Do NOT make connections based on a single word, topic, or demographic. "Bad Moms" (a comedy movie) does NOT connect to a parenting self-help book. That is a keyword match, not a taste match.
- If you cannot find a genuine cross-medium connection, recommend popular items in the same genre/tone instead. A good mainstream pick is always better than a forced obscure connection.
- It is OK to return fewer items if the profile doesn't support confident recommendations. Empty sections are better than bad recommendations.
- NEVER recommend practical/self-help/how-to books unless the user's profile explicitly shows they rate that category highly.
- SCHOLARLY/ACADEMIC CONTENT: Do NOT recommend academic texts, university press books, research monographs, or textbook-style titles UNLESS the user's profile shows a clear, strong pattern of engaging with that kind of content (multiple scholarly titles rated 8+, across multiple entries — not just one or two). With fewer than 150 rated items, default to mainstream: popular fiction, bestselling nonfiction (memoirs, true crime, narrative nonfiction, big-idea books), and well-known entertainment. A great popular recommendation is ALWAYS better than an impressive-sounding obscure one. When in doubt, go mainstream.

You are producing FOUR outputs in one JSON response — do NOT repeat the same items across sections:

1. top_picks: 8 recommendations total — 2 movies, 2 TV shows, 2 books, 2 podcasts. List the strongest pick first in each pair. The app will drop anything the user already has and keep the strongest surviving pick per category.
2. suggestions: 5 items for each of these categories: {', '.join(missing_types_list) if missing_types_list else '(none needed)'}. These should be DIFFERENT from top_picks. The app filters these too and keeps the top 3 survivors per category.
3. themes: 8 picks for EACH of these life-context themes — each theme is framed around a moment in the user's day, not a vibe in the abstract. Pick items that actually match the moment AND the user's taste profile. Don't repeat items across themes or with top_picks / suggestions. Theme slugs + what each is asking for:
{theme_guide}
4. insights: 3 sharp, specific observations about cross-medium patterns in their profile.

PREDICTED RATINGS — CRITICAL:
Every item in top_picks and every item in themes MUST include a "predicted_rating" field: your honest 1-5 prediction (with one decimal) of how this specific user would actually rate the item, based on their taste profile.
- Be ruthlessly honest. If a pick genuinely fits the moment but doesn't match the user's taste register (cozy family film for a prestige-drama person, YA for a literary reader, broad comedy for a dark-comedy person), predict LOW — 2 or 2.5 — don't soft-pedal. The app drops anything below 3, so lying gets the item dropped later anyway.
- Their taste register is visible in the PROFILE above. If they rate prestige TV 5/5 and cozy family movies aren't in their profile at all, a Paddington-style pick should be a 2.5 at best for them, not a 4.
- A score of 4+ means "this person will probably love this." 3.5 means "solid match." 3 means "borderline — worth trying but not a sure thing." Below 3 means "outside their lane."
- DO NOT inflate. Spread the ratings across the range. It is better to return fewer high-confidence picks than to lie up.

RECENCY BALANCE — CRITICAL:
The "recently rated" section is ONE signal among many. Do NOT over-index on the last item rated or the most recent few. If someone just rated a cooking show 5/5, that doesn't mean every recommendation should be food-related. Use the FULL taste profile — the breadth of their highly-rated items across genres, media types, and years — as the primary driver. Recent ratings are a tiebreaker, not a pivot.

NONFICTION IS WELCOME:
- Movies can include documentaries
- Books can be memoirs, essays, idea books, narrative nonfiction
- Podcasts can be interview, science, news, explainer
Match the user's fiction/nonfiction balance.

GENRE DEPTH vs EXPOSURE — CRITICAL:
One or two items in a genre does NOT mean the user is a fan of that genre. Someone who watched Spirited Away does not want niche anime. Someone who read one thriller does not want serial-killer deep cuts. Look at DENSITY: how many items in the genre, how highly rated, how recently consumed. A single 3/5 in a genre means casual exposure. Five 5/5s in a genre means genuine enthusiasm. Only recommend deep-genre picks when the profile shows genuine depth in that genre. Otherwise, stick to accessible, widely-known titles.

REASON FORMAT — CRITICAL:
Each "reason" field MUST have TWO parts:
1. WHAT IT IS: A 1-sentence description of the actual item — what it's about, the premise, the hook. The user has never heard of this and needs to know what they're looking at.
2. WHY YOU'LL LIKE IT: Why this specific user will enjoy it, citing a concrete connection to a specific item from a DIFFERENT media type in their profile.
Example: "A sci-fi thriller about a man who wakes up with no memory on a deep-space mission to save Earth. You loved The Martian's problem-solving energy and Severance's identity crisis — this hits both."

CRITICAL RULES:
- The connection in the reason MUST be CONCRETE — shared theme, idea, emotional beat, narrative approach. Never match on surface features like setting, demographic, or keyword.
- The no-surface-match rule applies to themes too. A shared word in the title is NOT a connection. A shared setting alone is NOT a connection. A shared genre label is NOT a connection. Example of what NOT to do: anchor is "The Florida Project" (a Sean Baker movie about poverty and childhood on the margins of Orlando); picking "Probate and Settle an Estate in Florida" (a legal how-to guide) is a surface match on the word "Florida" — it is NOT a valid theme pick. A valid match would be something like "Random Family" by Adrian Nicole LeBlanc, which shares the concrete themes of marginalized families and structural precarity.
- DO NOT recommend any of these — the user has already consumed, queued, or dismissed them: {avoid_str}
- Insights must reference actual items from their profile. Bad: "You like drama". Good: "Your top-rated book (The Road) and your top-rated TV show (The Last of Us) both center on post-apocalyptic parent-child journeys."

Return ONLY valid JSON, no markdown:
{{
  "top_picks": [
    {{"title": "...", "creator": "author or director name", "media_type": "movie", "year": 2020, "reason": "What it is + why you'll like it", "predicted_rating": 4.5}},
    ... 8 items total, 2 per media type
  ],
{suggestions_schema}
{theme_schema}
  "insights": [
    {{"icon": "connection|trend|pattern|shift", "text": "specific cross-medium insight citing real items"}},
    {{"icon": "...", "text": "..."}},
    {{"icon": "...", "text": "..."}}
  ]
}}"""

        text = (await generate(prompt)).strip()
        parsed = _parse_ai_json(text, "home_bundle")
        if not isinstance(parsed, dict):
            return empty_bundle

        # Normalize
        raw_top_picks = parsed.get("top_picks", []) or []
        raw_suggestions = parsed.get("suggestions", {}) or {}
        raw_themes = parsed.get("themes", {}) or {}
        raw_insights = parsed.get("insights", []) or []

        # Drop any pick/suggestion/theme already in the library before enriching.
        raw_top_picks = [p for p in raw_top_picks if not _is_known(p.get("title", ""), known_normalized)]
        for mt in list(raw_suggestions.keys()):
            items = raw_suggestions[mt]
            if isinstance(items, list):
                raw_suggestions[mt] = [
                    it for it in items if not _is_known(it.get("title", ""), known_normalized)
                ]
        # Themes that allow familiar/comfort rewatches skip the known-title filter
        COMFORT_THEMES = {"wind_down", "background_work"}
        for theme_slug in list(raw_themes.keys()):
            items = raw_themes[theme_slug]
            if isinstance(items, list) and theme_slug not in COMFORT_THEMES:
                raw_themes[theme_slug] = [
                    it for it in items if not _is_known(it.get("title", ""), known_normalized)
                ]

        # Enrich top picks and suggestions with posters in parallel.
        def _coerce_pr(raw) -> float | None:
            try:
                pr = float(raw)
            except (TypeError, ValueError):
                return None
            if pr <= 0 or pr > 10:
                return None
            return round(pr, 1)

        async def enrich_pick(pick: dict, allow_known: bool = False) -> dict | None:
            title = pick.get("title", "")
            mt = pick.get("media_type")
            creator = pick.get("creator") or pick.get("author") or ""
            pr = _coerce_pr(pick.get("predicted_rating"))
            # Search with creator for accuracy, fall back to title-only if no results
            matches = []
            if creator:
                try:
                    matches = await unified_search(f"{title} {creator}", mt)
                except Exception:
                    pass
            if not matches:
                try:
                    matches = await unified_search(title, mt)
                except Exception:
                    matches = []
            matches = _rank_by_title_match(title, matches, prefer_type=mt)
            if matches:
                best = matches[0]
                if not allow_known and _is_known(best.title, known_normalized):
                    return None
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
                    "predicted_rating": pr,
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
                "predicted_rating": pr,
            }

        async def enrich_suggestion(item: dict, media_type: str) -> dict | None:
            title = item.get("title", "")
            creator = item.get("creator") or item.get("author") or ""
            pr = item.get("predicted_rating")
            matches = []
            if creator:
                try:
                    matches = await unified_search(f"{title} {creator}", media_type)
                except Exception:
                    pass
            if not matches:
                try:
                    matches = await unified_search(title, media_type)
                except Exception:
                    matches = []
            matches = _rank_by_title_match(title, matches, prefer_type=media_type)
            if matches:
                best = matches[0]
                if _is_known(best.title, known_normalized):
                    return None
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

        # Process up to 8 top_picks (2 per media type) so filters can
        # drop known items without leaving the UI with one or zero picks.
        pick_tasks = [enrich_pick(p) for p in raw_top_picks[:8]]
        suggestion_tasks = []
        suggestion_keys: list[str] = []
        for mt, items in raw_suggestions.items():
            if not isinstance(items, list):
                continue
            for it in items[:5]:  # cap input per category at 5
                suggestion_tasks.append(enrich_suggestion(it, mt))
                suggestion_keys.append(mt)

        theme_tasks = []
        theme_keys: list[str] = []
        for theme_slug, items in raw_themes.items():
            if not isinstance(items, list):
                continue
            for it in items[:8]:  # cap input per theme at 8
                theme_tasks.append(enrich_pick(it, allow_known=(theme_slug in COMFORT_THEMES)))
                theme_keys.append(theme_slug)

        all_results = await asyncio.gather(*pick_tasks, *suggestion_tasks, *theme_tasks)
        pick_end = len(pick_tasks)
        sugg_end = pick_end + len(suggestion_tasks)

        # Minimum predicted rating to surface an item. Anything below this
        # is "outside the user's lane" per the prompt contract; we drop it
        # rather than show a bad match.
        MIN_PRED_RATING = 3.0

        def _pr_sort_key(item: dict) -> float:
            # None predictions sort to the bottom so legit scored items win
            # every tie. Negative for descending sort.
            pr = item.get("predicted_rating")
            return -(pr if isinstance(pr, (int, float)) else -1)

        def _has_min_pr(item: dict) -> bool:
            pr = item.get("predicted_rating")
            if pr is None:
                # Missing predictions pass through (enrichment couldn't
                # attach one). We don't punish for the AI forgetting.
                return True
            return pr >= MIN_PRED_RATING

        # Keep one top_pick per media type, preferring the higher
        # predicted rating, then the AI's ordering as tie-breaker.
        raw_survivors = [r for r in all_results[:pick_end] if r is not None and _has_min_pr(r)]
        raw_survivors.sort(key=_pr_sort_key)
        enriched_picks: list[dict] = []
        seen_types: set[str] = set()
        for r in raw_survivors:
            mt = r.get("media_type")
            if mt in seen_types:
                continue
            seen_types.add(mt)
            enriched_picks.append(r)

        enriched_suggestions: dict[str, list] = {}
        for key, result in zip(suggestion_keys, all_results[pick_end:sugg_end]):
            if result is None or not _has_min_pr(result):
                continue
            enriched_suggestions.setdefault(key, []).append(result)
        # Sort desc by predicted_rating, then cap at 3 per category
        for key in list(enriched_suggestions.keys()):
            enriched_suggestions[key].sort(key=_pr_sort_key)
            enriched_suggestions[key] = enriched_suggestions[key][:3]

        enriched_themes: dict[str, list] = {}
        for key, result in zip(theme_keys, all_results[sugg_end:]):
            if result is None:
                continue
            # For themes, keep items even without a predicted_rating —
            # the AI already matched them to the user's taste + the
            # moment. Dropping them leaves sparse sections.
            enriched_themes.setdefault(key, []).append(result)
        # Sort scored items first (desc), unscored at end, cap at 6
        for key in list(enriched_themes.keys()):
            enriched_themes[key].sort(key=_pr_sort_key)
            enriched_themes[key] = enriched_themes[key][:4]

        log.info(
            "home_bundle [user=%d]: %d top_picks, suggestions=%s, themes=%s, %d insights",
            user.id, len(enriched_picks),
            ", ".join(f"{k}={len(v)}" for k, v in enriched_suggestions.items()) or "none",
            ", ".join(f"{k}={len(v)}" for k, v in enriched_themes.items()) or "none",
            len(raw_insights),
        )
        # Fetch streaming providers for movie/TV top_picks only (not themes —
        # too many calls). Themes get providers via lazy client-side fetch.
        from app.services.tmdb import get_watch_providers
        for item in enriched_picks:
            if item.get("media_type") in ("movie", "tv") and item.get("external_id"):
                try:
                    item["watch_providers"] = await get_watch_providers(item["media_type"], item["external_id"])
                except Exception:
                    pass

        bundle = {
            "top_picks": enriched_picks,
            "suggestions": enriched_suggestions,
            "themes": enriched_themes,
            "insights": raw_insights,
        }
        cache.set(cache_key, bundle, ttl_seconds=21600)  # 6 hours
        return bundle
    except Exception as e:
        log.error("home_bundle failed: %s", str(e))
        return empty_bundle


@router.get("/best-bet/{media_type}")
async def best_bet(
    media_type: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    refresh: bool = Query(False),
):
    """Return ONE hero recommendation for this media type, explicitly
    anchored to something the user recently rated very highly.

    The point of "Your best bet" on the per-type library page isn't
    to be another random AI rec — it's to name WHY this one pick is
    special. We pick an anchor (a recently rated 5/5 item from
    ANY media type), then ask the AI for a single cross-medium rec
    in the requested type that's specifically tied to a concrete
    element of the anchor. Returns {pick, anchor, reason}.

    Cached 7 days per (user, media_type). Bustable with ?refresh=1."""
    import asyncio
    from datetime import datetime, timedelta

    from app import cache
    from app.config import settings
    from app.models import MediaEntry
    from app.services.unified_search import unified_search

    if media_type not in ("movie", "tv", "book", "podcast"):
        raise HTTPException(status_code=400, detail="Invalid media type")

    cache_key = f"best_bet:{user.id}:{media_type}"
    if refresh:
        cache.invalidate(cache_key)
    else:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    if not settings.gemini_api_key:
        return {"pick": None, "anchor": None}

    # Gather the user's recently loved items (5/5) across ALL media
    # types. These are the pool the AI can draw connections from — it
    # picks the strongest 1-2 to cite rather than us pre-selecting one.
    sixty_days_ago = datetime.utcnow() - timedelta(days=60)
    recent_loved = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.rating.isnot(None),
            MediaEntry.rating == 5,
            MediaEntry.rated_at.isnot(None),
            MediaEntry.rated_at >= sixty_days_ago,
        )
        .order_by(MediaEntry.rated_at.desc())
        .limit(8)
        .all()
    )
    if not recent_loved:
        recent_loved = (
            db.query(MediaEntry)
            .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None), MediaEntry.rating >= 4)
            .order_by(MediaEntry.rating.desc(), MediaEntry.created_at.desc())
            .limit(8)
            .all()
        )

    if not recent_loved:
        return {"pick": None, "anchor": None, "message": "Rate a few items 5/5 to unlock your best bet."}

    # For new profiles (under 14 days old), sort by rating rather than
    # recency — recency is noise when the user is still bulk-adding.
    _oldest = db.query(MediaEntry.created_at).filter(
        MediaEntry.user_id == user.id
    ).order_by(MediaEntry.created_at.asc()).first()
    _profile_age = (datetime.utcnow() - _oldest.created_at).days if _oldest and _oldest.created_at else 0
    if _profile_age < 14:
        recent_loved.sort(key=lambda e: -(e.rating or 0))

    loved_lines: list[str] = []
    for e in recent_loved:
        g = f" [{e.genres}]" if e.genres else ""
        loved_lines.append(
            f"  - {e.title} ({e.media_type}, {e.year or '?'}) — {e.rating}/5{g}"
        )
    loved_block = "RECENTLY LOVED (rated 4-5 — draw your connections from these):\n" + "\n".join(loved_lines) + "\n"

    known_normalized, _ = _build_known_titles(db, user.id)

    # Broader taste profile for register calibration. Top rated items
    # the user has engaged with across all media types.
    top_rated = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.rating.isnot(None),
            MediaEntry.rating >= 4,
        )
        .order_by(MediaEntry.rating.desc(), MediaEntry.rated_at.desc().nullslast())
        .limit(12)
        .all()
    )
    seen_titles = {e.title for e in recent_loved}
    taste_lines: list[str] = []
    for e in top_rated:
        if e.title in seen_titles:
            continue
        g = f" [{e.genres}]" if e.genres else ""
        taste_lines.append(
            f"  - {e.title} ({e.media_type}, {e.year or '?'}) — {e.rating}/5{g}"
        )
    taste_profile_block = (
        "BROADER TASTE PROFILE (calibrate register, tone, and ambition level):\n"
        + "\n".join(taste_lines)
        + "\n"
    ) if taste_lines else ""

    try:
        from app.services.gemini import generate

        type_label = {"movie": "movie", "tv": "TV show", "book": "book", "podcast": "podcast"}[media_type]
        resonance_signals = build_resonance_block(db, user.id)
        rec_feedback = build_rec_feedback_block(db, user.id)

        from app.services.taste_quiz_scoring import load_streaming_services
        from app.services.tmdb import TIER1_PROVIDERS
        bb_user_services = load_streaming_services(db, user.id)
        if bb_user_services and media_type in ("movie", "tv"):
            bb_service_names = [TIER1_PROVIDERS.get(pid, f"Service {pid}") for pid in bb_user_services]
            bb_streaming_ctx = f"\nSTREAMING: The user subscribes to: {', '.join(bb_service_names)}. Strongly prefer items available on these services. If recommending something on a service they don't have, note that it's available to rent/buy — this is acceptable for exceptional fits, but most picks should be streamable tonight.\n"
        else:
            bb_streaming_ctx = ""

        prompt = f"""You're picking ONE {type_label} as a hero recommendation. Below are items this user recently rated 4 or 5 out of 5 — your job is to find the strongest thematic bridge from ANY of them (one or two) to a great {type_label} they haven't seen yet.

{resonance_signals}
{rec_feedback}
{loved_block}
{taste_profile_block}{bb_streaming_ctx}
TASK: Generate 3 candidate {type_label}s. For each, find the deepest connection to ONE or TWO items from the RECENTLY LOVED list above. You choose which loved item(s) to cite — pick whichever create the most interesting, non-obvious bridge to your candidate. Different candidates SHOULD cite different loved items when possible.

CRITICAL — NO SURFACE MATCHES:
A shared word in the title is NOT a connection. A shared setting alone is NOT a connection. A shared genre label is NOT a connection. A shared demographic is NOT a connection. If you cannot articulate the connection without repeating a surface word, you haven't found one.

NEVER recommend practical/self-help/how-to books unless the user's profile explicitly shows they love that category. Stick to entertainment — fiction, narrative nonfiction, stories.

RULES:
- Each candidate must be a real, findable {type_label} — no invented titles.
- DO NOT pick anything the user already has in their library: {', '.join(list(known_normalized)[:30]) if known_normalized else 'none'}
- Each "reason" must have EXACTLY TWO short sentences (total under 40 words): (1) What it is — one punchy premise sentence. (2) Why — "Because you loved [Title], ..." or "Because you loved [Title] and [Title], ..." citing a specific concrete connection. No run-on clauses.
- Different candidates should cite DIFFERENT items from the loved list when possible — don't anchor everything to the same item.
- ALWAYS include a "creator" field with the author, director, or creator name.
- Include "cited" — an array of 1-2 title strings from the loved list that this candidate connects to.
- Match audience and tonal register. Use the BROADER TASTE PROFILE to calibrate.
- Include a "predicted_rating": your honest 1-5 prediction (one decimal). Be ruthless — predict LOW (2-2.5) if the fit is weak. The app drops anything below 3. It is fine for ALL candidates to score below 3.
- Spread your scores across the range. Don't give all three 4+.

Return ONLY valid JSON, no markdown:
{{
  "candidates": [
    {{
      "title": "...",
      "creator": "author/director/creator name",
      "year": 2020,
      "cited": ["Silo"],
      "reason": "A trapped crew unravels a conspiracy aboard a deep-space ark. Because you loved Silo, the same slow-burn paranoia of living inside a lie.",
      "predicted_rating": 4.5
    }},
    {{
      "title": "...",
      "creator": "...",
      "year": 2018,
      "cited": ["Into the Wild", "Severance"],
      "reason": "Short punchy premise. Because you loved Into the Wild and Severance, one concrete connection.",
      "predicted_rating": 3.5
    }},
    {{
      "title": "...",
      "creator": "...",
      "year": 2022,
      "cited": ["The Florida Project"],
      "reason": "Short punchy premise. Because you loved The Florida Project, one concrete connection.",
      "predicted_rating": 3.2
    }}
  ]
}}"""

        raw_text = (await generate(prompt)).strip()
        log.info(
            "best_bet [user=%d/%s] raw_response: %s",
            user.id, media_type, raw_text[:1200],
        )
        parsed = _parse_ai_json(raw_text, f"best_bet:{media_type}")
        if not isinstance(parsed, dict):
            return {"pick": None, "anchor": None}

        raw_candidates = parsed.get("candidates") or []
        if not isinstance(raw_candidates, list) or not raw_candidates:
            return {"pick": None, "anchor": None}

        # Normalize each candidate: coerce the rating, drop anything the
        # user already has, drop anything below the 3 floor, then sort
        # descending. If everything lands below 3, we return no pick
        # rather than force a bad one onto the card.
        def _coerce_pr(raw) -> float | None:
            try:
                v = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                return None
            if v is None or v <= 0 or v > 5:
                return None
            return round(v, 1)

        survivors: list[dict] = []
        for c in raw_candidates:
            if not isinstance(c, dict):
                continue
            t = (c.get("title") or "").strip()
            if not t or _is_known(t, known_normalized):
                continue
            pr = _coerce_pr(c.get("predicted_rating"))
            if pr is None or pr < 3.0:
                continue
            cited = c.get("cited") or []
            if isinstance(cited, str):
                cited = [cited]
            survivors.append({
                "title": t,
                "year": c.get("year"),
                "reason": c.get("reason", ""),
                "predicted_rating": pr,
                "creator": c.get("creator") or "",
                "cited": cited,
            })

        if not survivors:
            log.info(
                "best_bet [user=%d/%s]: all candidates dropped (known or below 3.0)",
                user.id, media_type,
            )
            return {
                "pick": None,
                "anchor": None,
                "message": "Nothing crossed the 3/5 bar for this category right now — try again in a few days.",
            }

        survivors.sort(key=lambda c: -c["predicted_rating"])
        chosen = survivors[0]
        title = chosen["title"]
        pr = chosen["predicted_rating"]
        cited_titles = chosen.get("cited") or []

        # Enrich via search — try with creator first, fall back to title-only
        creator = chosen.get("creator") or ""
        matches = []
        if creator:
            try:
                matches = await unified_search(f"{title} {creator}", media_type)
            except Exception:
                pass
        if not matches:
            try:
                matches = await unified_search(title, media_type)
            except Exception:
                matches = []
        matches = _rank_by_title_match(title, matches, prefer_type=media_type)
        enriched_pick: dict | None = None
        if matches:
            best = matches[0]
            if not _is_known(best.title, known_normalized):
                enriched_pick = {
                    "title": best.title,
                    "media_type": best.media_type,
                    "year": best.year,
                    "image_url": best.image_url,
                    "external_id": best.external_id,
                    "source": best.source,
                    "creator": best.creator,
                    "genres": best.genres or [],
                    "description": best.description,
                    "reason": chosen["reason"],
                    "predicted_rating": pr,
                }
        if not enriched_pick:
            enriched_pick = {
                "title": title,
                "media_type": media_type,
                "year": chosen.get("year"),
                "image_url": None,
                "external_id": "",
                "source": "",
                "creator": None,
                "genres": [],
                "description": None,
                "reason": chosen["reason"],
                "predicted_rating": pr,
            }

        # Fetch streaming providers for movie/TV picks
        if enriched_pick.get("source") == "tmdb" and enriched_pick.get("external_id") and media_type in ("movie", "tv"):
            try:
                from app.services.tmdb import get_watch_providers
                enriched_pick["watch_providers"] = await get_watch_providers(media_type, enriched_pick["external_id"])
            except Exception:
                pass

        result = {
            "pick": enriched_pick,
            "anchor": {
                "title": cited_titles[0] if cited_titles else None,
            } if cited_titles else None,
            "cited": cited_titles,
        }
        log.info(
            "best_bet [user=%d/%s]: cited=%s -> picked %s (pred=%s) from %d surviving candidates",
            user.id, media_type, cited_titles, enriched_pick["title"], pr, len(survivors),
        )
        cache.set(cache_key, result, ttl_seconds=604800)  # 7 days
        return result
    except Exception as e:
        log.exception("best_bet failed for %s: %s", media_type, str(e))
        return {"pick": None, "anchor": None}


# ---------------------------------------------------------------------------
# Home "Right Now" block: lightweight, currently-consuming-centered
# ---------------------------------------------------------------------------


class ResonanceRequest(BaseModel):
    entry_id: int


@router.post("/home/resonance")
async def post_home_resonance(
    req: ResonanceRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Toggle the 'resonating right now' flag for a currently-consuming
    entry. Validates the entry belongs to the caller. Busts the cached
    right-now bundle so the next load reflects the change. Returns the
    new flag state."""
    from app.models import MediaEntry
    from app import cache

    entry = (
        db.query(MediaEntry)
        .filter(MediaEntry.id == req.entry_id, MediaEntry.user_id == user.id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    is_on = toggle_home_resonance(db, user.id, req.entry_id)
    # Bust caches that include resonance hints so the next render
    # reflects the new signal.
    cache.invalidate(f"right_now:{user.id}")
    cache.invalidate(f"home_bundle:{user.id}")
    return {"entry_id": req.entry_id, "resonating": is_on}


@router.get("/home/right-now")
async def get_home_right_now(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    refresh: bool = Query(False),
):
    """Return the data for the home page's 'Right Now' block:
    the user's currently-consuming items + a one-sentence AI
    commentary on the intersection of what they're in the middle of.

    Cached 12h per user. The cache key includes a hash of the
    current consuming-entry ids so adding/removing a 'consuming'
    item busts the cache automatically."""
    import hashlib

    from app import cache
    from app.config import settings
    from app.models import MediaEntry

    consuming = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.status == "consuming")
        .order_by(MediaEntry.updated_at.desc())
        .limit(6)
        .all()
    )

    resonance = get_home_resonance(db, user.id)

    def _item_dict(e):
        return {
            "id": e.id,
            "title": e.title,
            "media_type": e.media_type,
            "year": e.year,
            "image_url": e.image_url,
            "external_id": e.external_id,
            "source": e.source,
            "is_resonating": str(e.id) in resonance,
        }

    if not consuming:
        return {"commentary": "", "items": []}

    # Cache-key hash covers the consuming ids so moving items in or out
    # of "consuming" automatically yields a fresh commentary.
    ids_sig = ",".join(str(e.id) for e in consuming)
    sig = hashlib.md5(ids_sig.encode()).hexdigest()[:8]
    cache_key = f"right_now:{user.id}:{sig}"
    if refresh:
        cache.invalidate(cache_key)
    else:
        cached = cache.get(cache_key)
        if cached is not None:
            # Re-decorate with fresh resonance state in case the user
            # toggled a chip; the commentary itself is stable though.
            cached_items = cached.get("items") or []
            for ci in cached_items:
                ci["is_resonating"] = str(ci.get("id")) in resonance
            return cached

    items = [_item_dict(e) for e in consuming]

    commentary = ""
    if settings.gemini_api_key and len(consuming) >= 2:
        try:
            from app.services.gemini import generate

            lines = [
                f"  - {e.title} ({e.media_type}, {e.genres or 'unknown genre'})"
                for e in consuming
            ]
            prompt = f"""You are writing ONE sentence — warm, specific, insightful — about the intersection of the media this user is currently in the middle of. The goal is to name, in plain words, the through-line across these items: the tonal register, the idea they keep circling, the kind of emotional territory they're walking through right now. Cite at least ONE of the items by name.

CURRENTLY CONSUMING:
{chr(10).join(lines)}

RULES:
- ONE sentence only. 25-40 words.
- Plain prose. No metaphors piled on metaphors. No "it's almost as if…".
- Commit to the observation.
- If the items genuinely don't intersect, say that plainly: "You've got a wide net cast right now — {{pick one}} is the outlier." Don't force a connection.

Return ONLY the sentence, no quotes, no preamble."""
            text = (await generate(prompt)).strip()
            # Strip any stray surrounding quotes
            text = text.strip('"\u201c\u201d ').strip()
            if text and len(text) <= 400:
                commentary = text
        except Exception as e:
            log.warning("right_now commentary failed: %s", str(e))

    result = {"commentary": commentary, "items": items}
    cache.set(cache_key, result, ttl_seconds=43200)  # 12 hours
    return result


@router.get("/new-releases/{media_type}")
async def new_releases(
    media_type: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    refresh: bool = Query(False),
):
    """Surface what's currently new/hot in a given media type and attach
    a per-user predicted-rating score to each item. Cached for 7 days
    per user, bustable with ?refresh=1. Used by the per-type profile
    pages to answer 'what's in theaters / new to streaming / new
    podcasts / new books'."""
    import asyncio
    import json

    from app import cache
    from app.config import settings
    from app.models import MediaEntry

    if media_type not in ("movie", "tv", "book", "podcast"):
        raise HTTPException(status_code=400, detail="Invalid media type")

    cache_key = f"new_releases:{user.id}:{media_type}"
    if refresh:
        cache.invalidate(cache_key)
    else:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    # 1) Fetch raw "what's new" from the right external API.
    # Pull a wide pool (30 per sub-section) so we have enough signal left
    # after filtering out low-predicted items and items the user already has.
    raw_items: list = []
    sections: list[tuple[str, list]] = []
    try:
        if media_type == "movie":
            from app.services.tmdb import get_movies_now_playing, get_movies_popular
            now_playing, popular = await asyncio.gather(
                get_movies_now_playing(limit=60),
                get_movies_popular(limit=30),
            )
            # Deduplicate by external_id — popular often overlaps now_playing
            seen_ids: set[str] = set()
            np_items = []
            for item in now_playing:
                if item.external_id not in seen_ids:
                    np_items.append(item)
                    seen_ids.add(item.external_id)
            streaming_items = []
            for item in popular:
                if item.external_id not in seen_ids:
                    streaming_items.append(item)
                    seen_ids.add(item.external_id)
            sections = [
                ("In theaters", np_items),
                ("Popular on streaming", streaming_items),
            ]
        elif media_type == "tv":
            from app.services.tmdb import get_tv_on_the_air, get_tv_popular
            on_air, popular = await asyncio.gather(
                get_tv_on_the_air(limit=30),
                get_tv_popular(limit=30),
            )
            seen_ids = set()
            oa_items = []
            for item in on_air:
                if item.external_id not in seen_ids:
                    oa_items.append(item)
                    seen_ids.add(item.external_id)
            pop_items = []
            for item in popular:
                if item.external_id not in seen_ids:
                    pop_items.append(item)
                    seen_ids.add(item.external_id)
            sections = [
                ("Currently airing", oa_items),
                ("Popular on streaming", pop_items),
            ]
        elif media_type == "book":
            # NYT bestsellers are the ONLY source for books. Open Library
            # search surfaces self-published spam, AI-generated slop, and
            # non-English editions even with filters — it's not fit for
            # purpose as a "what's new" feed. If NYT_API_KEY isn't
            # configured we return an empty section and the page shows
            # "nothing to surface this week" rather than serving junk.
            from app.services.nyt_books import get_bestsellers
            nyt_sections = await get_bestsellers(limit_per_list=15)
            if not nyt_sections:
                log.warning(
                    "new_releases [book/user=%d]: NYT returned no sections "
                    "(NYT_API_KEY configured=%s). Showing empty feed — set "
                    "NYT_API_KEY on Cloud Run to enable the books feed.",
                    user.id, bool(settings.nyt_api_key),
                )
            sections = nyt_sections
        elif media_type == "podcast":
            from app.services.itunes import get_top_podcasts
            podcasts = await get_top_podcasts(limit=30)
            sections = [("Top podcasts right now", podcasts)]
    except Exception as e:
        log.error("new_releases fetch failed for %s: %s", media_type, str(e))
        return {"sections": [], "updated_at": None}

    # Strip out anything the user already has OR has dismissed
    known_normalized, _ = _build_known_titles(db, user.id)
    log.info(
        "new_releases filter [%s/user=%d]: %d known titles, %d raw items pre-filter",
        media_type, user.id, len(known_normalized),
        sum(len(items) for _, items in sections),
    )
    filtered_sections: list[tuple[str, list]] = []
    dropped_count = 0
    for label, items in sections:
        kept = []
        for it in items:
            if _is_known(it.title, known_normalized):
                log.info(
                    "new_releases [%s/user=%d]: dropping '%s' (normalized='%s') — already known",
                    media_type, user.id, it.title, _normalize_title(it.title),
                )
                dropped_count += 1
                continue
            kept.append(it)
        if kept:
            filtered_sections.append((label, kept))
    log.info(
        "new_releases filter [%s/user=%d]: dropped %d items, %d sections remain",
        media_type, user.id, dropped_count, len(filtered_sections),
    )

    if not filtered_sections:
        from datetime import datetime as _dt
        result = {"sections": [], "updated_at": _dt.utcnow().isoformat()}
        cache.set(cache_key, result, ttl_seconds=604800)
        return result

    # 2) Ask Gemini to predict how much this user would like each item.
    predicted_map: dict[str, float | None] = {}
    if settings.gemini_api_key:
        try:
            from app.models import DismissedItem

            # Pull three distinct signals about the user's taste:
            #   (a) Top-rated items — what they love
            #   (b) Low-rated items (<=2/5) — what they actively dislike
            #   (c) Dismissed items — what they looked at and explicitly rejected
            # Gemini sees all three so it can score harshly when a
            # candidate resembles a dislike or a dismissal.
            top_rated = (
                db.query(MediaEntry)
                .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None))
                .order_by(MediaEntry.rating.desc())
                .limit(20)
                .all()
            )
            low_rated = (
                db.query(MediaEntry)
                .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None), MediaEntry.rating <= 2)
                .order_by(MediaEntry.rating.asc())
                .limit(15)
                .all()
            )
            dismissed = (
                db.query(DismissedItem.title, DismissedItem.media_type)
                .filter(DismissedItem.user_id == user.id)
                .limit(20)
                .all()
            )

            taste_lines = [
                f"- {e.title} ({e.media_type}, {e.rating}/5) [{e.genres or ''}]"
                for e in top_rated
            ]
            taste_summary = "\n".join(taste_lines) if taste_lines else "no profile yet"

            dislike_lines = [
                f"- {e.title} ({e.media_type}, {e.rating}/5) [{e.genres or ''}]"
                for e in low_rated
            ]
            dislikes_summary = "\n".join(dislike_lines) if dislike_lines else "none recorded"

            dismissed_lines = [f"- {title} ({mt})" for title, mt in dismissed]
            dismissed_summary = "\n".join(dismissed_lines) if dismissed_lines else "none recorded"

            all_items_flat = []
            for _, items in filtered_sections:
                all_items_flat.extend(items)

            items_json = [
                {
                    "title": it.title,
                    "year": it.year,
                    "genres": it.genres or [],
                    "audience_score": it.audience_score,
                    "vote_count": it.audience_count,
                }
                for it in all_items_flat
            ]

            from app.services.gemini import generate

            prompt = f"""You are predicting how much this specific user would enjoy each of the candidate items below, on a 1-5 scale, OR returning null for items you cannot confidently score.

THE USER'S TASTE SIGNALS — READ ALL THREE:

LOVED (top-rated items they scored 4+):
{taste_summary}

ACTIVELY DISLIKED (rated 2 or below — this is what they DON'T want):
{dislikes_summary}

EXPLICITLY REJECTED (dismissed from recommendations — they saw these and said no):
{dismissed_summary}

SCORING RULES:
1. The 3.5 threshold: any score below 3.5 is HIDDEN from the user. So ~70% of what you see should score below 3.5, because most things in the wild aren't a fit for any specific person's taste. Only the genuine fits surface.
2. Weight the negative signals heavily. If a candidate resembles anything in DISLIKED or REJECTED — same genre, same tone, same subject matter, same audience — score it 1-2.5 even if it's popular or prestigious. The user has told us directly that stuff in those categories isn't for them.
3. When the candidate is a strong match to LOVED items — same genre, tone, and subject matter — score it 4-4.5. Only score 5 for a near-perfect match to one of their very top items.
4. When you don't have enough information to score confidently (genres are missing, you don't recognize the title, the description is too thin), RETURN null for that title. It's better to admit uncertainty than to guess — guessed scores clutter the user's feed with garbage.
5. Use the audience_score (TMDB 0-10 scale) as a quality signal. If a movie has an audience score below 5.0 with a meaningful number of votes (50+), be skeptical — it's probably not worth recommending unless it's an exact genre match for the user. Poorly-reviewed movies should need a stronger taste match to surface.
6. Ignore raw popularity and cultural importance. A #1 bestseller the user clearly wouldn't enjoy still gets a low score or null.
7. Do not inflate scores out of politeness. A rating of 2 that hides something the user wouldn't enjoy is better than a 3.5 that wastes their attention.

ITEMS TO SCORE:
{json.dumps(items_json, indent=2)}

Return ONLY a JSON object mapping each exact candidate title to either a number 1-5 (one decimal place) or null. No markdown, no preamble, no explanations.

{{"Title 1": 4.5, "Title 2": 1.5, "Title 3": null, ...}}"""

            text = (await generate(prompt)).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace >= 0 and last_brace > first_brace:
                text = text[first_brace : last_brace + 1]
            parsed = json.loads(text)
            # Keep nulls as None so the final filter knows to drop the
            # item rather than defaulting it to 0. Keys lowercased for
            # robust matching against MediaResult.title.lower().
            predicted_map = {}
            for k, v in parsed.items():
                key = str(k).lower()
                if v is None:
                    predicted_map[key] = None
                else:
                    try:
                        predicted_map[key] = float(v)
                    except (TypeError, ValueError):
                        predicted_map[key] = None
        except Exception as e:
            log.error("new_releases prediction failed: %s", str(e))

    # 3) Attach predicted scores to each item, sort each section by score,
    # and serialize for the client.
    def _serialize(item) -> dict:
        return {
            "title": item.title,
            "media_type": item.media_type,
            "year": item.year,
            "image_url": item.image_url,
            "external_id": item.external_id,
            "source": item.source,
            "creator": item.creator,
            "genres": item.genres or [],
            "description": item.description,
            "predicted_rating": predicted_map.get(item.title.lower()),
            "audience_score": item.audience_score,
            "audience_count": item.audience_count,
        }

    MIN_SCORE = 3.5
    MAX_PER_SECTION = 8
    serialized_sections = []
    for label, items in filtered_sections:
        rows = [_serialize(it) for it in items]
        # Drop nulls — AI couldn't score confidently, don't guess.
        scored = [r for r in rows if r["predicted_rating"] is not None and r["predicted_rating"] >= MIN_SCORE]
        scored.sort(key=lambda r: r["predicted_rating"], reverse=True)
        if scored:
            serialized_sections.append({"label": label, "items": scored[:MAX_PER_SECTION]})

    from datetime import datetime as _dt
    result = {"sections": serialized_sections, "updated_at": _dt.utcnow().isoformat()}
    cache.set(cache_key, result, ttl_seconds=604800)  # 7 days
    return result


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
    known_normalized, known_display = _build_known_titles(db, user.id)

    # Build cross-medium taste summary, grouped by type and weighted by recency
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    recent_items = []
    for e in entries:
        if e.rating and e.rating >= 4:
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
            lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/5 [{e.genres or ''}]" for e in items]
            taste_sections.append(f"{label} they rated highly:\n" + "\n".join(lines))

    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    recent_section = ""
    if recent_items:
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/5)" for e in recent_items[:10]]
        recent_section = f"\n\nRECENTLY RATED (last 30 days — their current mood, weight heavily):\n" + "\n".join(recent_lines)

    # Build an avoid list for the prompt — pass as many titles as we can
    # fit without blowing the prompt budget. Prioritize highly-rated items
    # first (AI is most tempted to re-recommend those), then the rest.
    highly_rated_titles = [e.title for e in entries if e.rating and e.rating >= 4]
    other_known = [t for t in known_display if t not in set(highly_rated_titles)]
    ordered_avoid = highly_rated_titles + other_known
    # Cap at ~6000 chars to stay well under token limits
    avoid_titles: list[str] = []
    char_budget = 6000
    for t in ordered_avoid:
        if char_budget <= 0:
            break
        avoid_titles.append(t)
        char_budget -= len(t) + 2
    avoid_str = ", ".join(avoid_titles) if avoid_titles else "none"

    try:
        from app.services.gemini import generate
        from app.services.taste_quiz_scoring import build_quiz_signals_block
        quiz_signals = build_quiz_signals_block(db, user.id)

        prompt = f"""You are a cross-medium taste expert. Your specialty is finding specific, real connections between books, TV, movies, and podcasts — fiction AND nonfiction — that share themes, ideas, tone, subject matter, or emotional register.

{quiz_signals}
USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}

TASK: Pick 8 recommendations — TWO movies, TWO TV shows, TWO books, TWO podcasts. I'm asking for two per category so I have a backup if one is already in the user's library; the app will keep the top-ranked survivor per category.

NONFICTION IS WELCOME:
- Movies can include documentaries (*My Octopus Teacher*, *The Social Dilemma*)
- Books can be literary nonfiction, memoirs, idea books, essays (*Sapiens*, *Educated*, *The Body Keeps the Score*)
- Podcasts can be interview, science, news, explainer (*Radiolab*, *The Daily*, *Hidden Brain*, *Ezra Klein Show*)
- Look at the user's profile — if they rate nonfiction or documentaries highly, recommend more of it. If they lean narrative, lean that way.

REASON FORMAT: Each "reason" MUST have TWO parts: (1) What it is — a 1-sentence premise so the user knows what they're looking at. (2) Why they'll like it — cite a specific item from their profile. Good examples:
- "The atmospheric dread of *Dune* (book) translates directly to this slow-burn sci-fi film."
- "You loved the careful character work in *The Wire* (TV) — this nonfiction book has the same patient, morally complex portrait of institutional failure."
- "If *Serial* (podcast) hooked you on ambiguity and moral inquiry, this documentary explores similar unresolved tension."
- "You gave *Educated* (book) a 5/5 — this film has the same aching quality of a young person finding their own voice against the weight of their family."

Rules:
- 8 items total: 2 movies, 2 tv, 2 books, 2 podcasts. List your strongest pick first in each pair.
- Each reason MUST cite an item from a DIFFERENT media type by name
- The connection must be CONCRETE — cite a shared theme, idea, emotional beat, or narrative approach. Never rely on shared demographic, setting, or keyword.
- If recently rated items suggest a mood shift, lean into that mood
- Do NOT recommend any of these (already in their library): {avoid_str}
- Pick bold, specific things they'll love — not generic bestsellers

Return ONLY valid JSON, no markdown — an array of 8 items:
[
  {{"title": "...", "media_type": "movie", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "movie", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "tv", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "tv", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "book", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "book", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "podcast", "year": 2020, "reason": "..."}},
  {{"title": "...", "media_type": "podcast", "year": 2020, "reason": "..."}}
]"""

        text = (await generate(prompt)).strip()
        picks = _parse_ai_json(text, "top_picks")
        if not isinstance(picks, list):
            return []

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

        # Filter out any AI picks that map to something already in the
        # user's library — check BOTH the AI's original title and the
        # enriched search result's title. The AI gave us 2 per category;
        # we want 1 surviving pick per category after filtering.
        unknown_picks = []
        for p in picks[:8]:
            ai_title = p.get("title", "")
            if _is_known(ai_title, known_normalized):
                log.info("top_picks: dropping AI pick '%s' — already in library", ai_title)
                continue
            unknown_picks.append(p)

        found = await asyncio.gather(*[search_pick(p) for p in unknown_picks])
        # Post-filter: the search can map a loose title to a canonical
        # one the user already owns.
        survivors = [
            r for r in found
            if r is not None and not _is_known(r["title"], known_normalized)
        ]
        # Keep one per media type, preferring the AI's own ordering (the
        # prompt asked it to list its strongest pick first in each pair).
        results: list = []
        seen_types: set[str] = set()
        for r in survivors:
            mt = r.get("media_type")
            if mt in seen_types:
                continue
            seen_types.add(mt)
            results.append(r)
        log.info(
            "top_picks [user=%d]: %d picks surfaced (%s)",
            user.id, len(results), ", ".join(sorted(seen_types)) or "none",
        )
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

    known_normalized, known_display = _build_known_titles(db, user.id)

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
        if e.rating and e.rating >= 4:
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
            lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/5" for e in items]
            taste_sections.append(f"{label}:\n" + "\n".join(lines))

    taste_summary = "\n\n".join(taste_sections) if taste_sections else "No rated items yet."

    recent_section = ""
    if recent_items:
        recent_items.sort(key=lambda e: e.rated_at, reverse=True)
        recent_lines = [f"  - {e.title} ({e.media_type}, {e.rating}/5)" for e in recent_items[:8]]
        recent_section = f"\n\nRECENTLY RATED (last 30 days — their current mood, weight heavily):\n" + "\n".join(recent_lines)

    type_labels = {"movie": "movies", "tv": "TV shows", "book": "books", "podcast": "podcasts"}
    missing_labels = [type_labels[t] for t in missing_types]

    # Pack the avoid list — cap at ~6000 chars to stay under token limits.
    avoid_titles: list[str] = []
    char_budget = 6000
    for t in known_display:
        if char_budget <= 0:
            break
        avoid_titles.append(t)
        char_budget -= len(t) + 2
    avoid_str = ", ".join(avoid_titles) if avoid_titles else "none"

    try:
        from app.services.gemini import generate
        from app.services.taste_quiz_scoring import build_quiz_signals_block
        quiz_signals = build_quiz_signals_block(db, user.id)

        prompt = f"""You are a cross-medium taste expert. Find connections between books, TV, movies, and podcasts — fiction AND nonfiction — that share themes, ideas, tone, or emotional register.

{quiz_signals}
USER'S TASTE PROFILE (across all media types):
{taste_summary}
{recent_section}

TASK: Suggest 5 items for EACH of these categories: {', '.join(missing_labels)}. I'm asking for 5 per category so I have backups — the app will filter out anything the user already has and show the top 3 survivors.

NONFICTION IS WELCOME:
- Movies include documentaries
- Books include memoirs, essays, idea books, narrative nonfiction
- Podcasts include interview, science, explainer, news
Look at the user's profile and match their fiction/nonfiction balance.

REASON FORMAT: Each "reason" MUST have TWO parts: (1) What it is — a 1-sentence premise so the user knows what they're looking at. (2) Why they'll like it — cite a specific item from their profile and name a concrete shared element. Never match on surface features.

Good example: "You gave *The Wire* (TV) a 5/5 — this nonfiction book on the war on drugs delivers the same unflinching institutional critique."
Bad example: "Both are about cities."

DO NOT recommend any of these titles — the user has already consumed, queued, or dismissed them: {avoid_str}

Return ONLY valid JSON, no markdown. Each category gets a list of 5 items, strongest first:
{{
  "movie": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 4.5}}, ... 5 items],
  "tv": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 4.5}}, ... 5 items],
  "book": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 4.5}}, ... 5 items],
  "podcast": [{{"title": "...", "year": 2020, "reason": "...", "predicted_rating": 4.5}}, ... 5 items]
}}

predicted_rating is 1-5 based on how much this user would enjoy it.
Only include categories from this list: {', '.join(missing_types)}"""

        text = (await generate(prompt)).strip()
        parsed = _parse_ai_json(text, "home_suggestions")
        if not isinstance(parsed, dict):
            return {"suggestions": {}}

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
                # Pre-filter: skip anything the user already has before we spend API calls.
                if _is_known(item.get("title", ""), known_normalized):
                    log.info("home_suggestions: dropping AI pick '%s' — already in library", item.get("title"))
                    continue
                all_tasks.append(enrich(item, media_type))
                task_keys.append(media_type)

        results = await asyncio.gather(*all_tasks)
        for key, result in zip(task_keys, results):
            # Post-filter: the search enrichment can map a loose AI title to a
            # canonical one the user already owns.
            if _is_known(result["title"], known_normalized):
                log.info("home_suggestions: dropping enriched '%s' — resolves to owned", result["title"])
                continue
            enriched.setdefault(key, []).append(result)

        # Cap at 3 per category — AI gives us up to 5, filters take some,
        # we keep the strongest survivors.
        for key in list(enriched.keys()):
            enriched[key] = enriched[key][:3]

        log.info(
            "home_suggestions [user=%d]: %s",
            user.id,
            ", ".join(f"{k}={len(v)}" for k, v in enriched.items()) or "empty",
        )
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

    # Per-user cache key — the AI's reasoning cites items from THIS user's
    # profile, so the output is not shareable across users. Use the
    # "related_items" prefix so the cache layer knows to keep it alive
    # until the profile changes.
    cache_key = f"related_items:{user.id}:{media_type}:{external_id}"
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
    taste_lines = [f"- {e.title} ({e.media_type}, {e.rating}/5)" for e in top_rated] if top_rated else []
    taste_summary = "\n".join(taste_lines) if taste_lines else "no profile yet"

    # Figure out which media types to recommend (all except current)
    other_types = [mt for mt in ("movie", "tv", "book", "podcast") if mt != media_type]
    type_labels = {"movie": "movies", "tv": "TV shows", "book": "books", "podcast": "podcasts"}
    other_labels = [type_labels[t] for t in other_types]

    item_desc = item.description[:300] if item.description else ""
    item_genres = ", ".join(item.genres) if item.genres else ""

    # Recently-recommended titles across this user's last ~60 related_items
    # calls. Used to diversify — without this, Gemini keeps falling back on
    # prestige TV defaults (Fleabag, Succession, The Bear, The Crown) for
    # anything it finds vaguely emotionally complex.
    recent_recs = cache.get_recent_recs(user.id)
    recent_recs_str = ", ".join(recent_recs[-40:]) if recent_recs else "none yet"

    try:
        from app.services.gemini import generate
        from app.services.taste_quiz_scoring import build_quiz_signals_block
        quiz_signals = build_quiz_signals_block(db, user.id)

        prompt = f"""You are a cross-medium taste expert. Given this media item, suggest 2 items from EACH OTHER media type that share a real, specific connection — theme, tone, subject matter, emotional register, ideas, or storytelling approach — AND are appropriate for the same audience and tonal register.

CURRENT ITEM: {item.title} ({media_type}, {item.year or '?'})
Genres: {item_genres}
Description: {item_desc}

{quiz_signals}
User's taste profile (for personalization):
{taste_summary}

TASK: Recommend 2 items each from: {', '.join(other_labels)}.

WHAT COUNTS AS A MEDIA ITEM (all valid):
- Fiction: novels, narrative films, scripted TV, storytelling podcasts
- Literary nonfiction: memoirs, biographies, essays, narrative journalism
- Idea books / popular nonfiction: *Sapiens*, *Atomic Habits*, *The Body Keeps the Score*
- Documentaries: *My Octopus Teacher*, *The Vow*, nature docs, true crime docs
- News, science, interview, and explanatory podcasts: *Radiolab*, *The Daily*, *Hidden Brain*
- Self-help and philosophy books are fine IF they match thematically AND tonally

WHAT TO AVOID: Pure reference/instructional material with no thematic voice — SAT prep, dictionaries, textbooks, software manuals, cookbooks without narrative.

DIVERSITY — DO NOT REPEAT YOURSELF:
The user has recently been shown these titles from previous related-items lookups: {recent_recs_str}
DO NOT recommend any of them again in this response. Pick something different even if your first instinct would be to reuse one — the user wants variety across the items they browse, not the same four or five prestige picks attached to everything.

ANTI-LOOP RULE:
Prestige titles (*Fleabag*, *Succession*, *The Bear*, *The Crown*, *Ted Lasso*, *Severance*, *Atlanta*, *Sapiens*, *Educated*, *The Body Keeps the Score*, *This American Life*, *Serial*, *Radiolab*, etc.) are genuinely great and may be perfectly appropriate recommendations — but you have a tendency to reach for them whenever the connection is fuzzy, which turns every detail page into the same four picks. It's fine to recommend one when the link is concrete and sharp. But if your first instinct is a famous prestige title AND the thematic link feels generic ("both explore complex emotions"), STOP and dig deeper — name a less-obvious item with a tighter fit instead. The goal is variety across the user's browsing session, not to blacklist any title.

AUDIENCE AND TONE — THIS IS A HARD CONSTRAINT:
Before you suggest anything, classify the current item along two axes:
  (a) Audience: family/kids, general-audience, or adult.
  (b) Tonal register: light/comic, warm/hopeful, contemplative, melancholy, grim/dark, intense/horror.

EVERY recommendation MUST match on BOTH axes. Do not cross these lines.
- If the current item is a family/kids movie (e.g. Genres include "Family" or "Animation", or the description is about children), NEVER recommend R-rated, adult, or grim/dark material — even if you can find a "theme" connection. Recommend other family-appropriate items OR warm contemplative material about the same ideas.
- If the current item is adult and dark, don't recommend kids material or frothy comedy.
- A sad movie gets meditative or hopeful-sad recommendations, not zany comedy or horror.
- A comedy gets other warm or witty material, not grim literary fiction.

CONNECTION RULES:
1. The connection MUST be real and specific. Reference a CONCRETE element from the current item.
2. Cross-medium connections can span fiction and nonfiction BOTH WAYS, but audience/tone still governs.
3. GOOD example: "*Lady Bird* captures the raw self-consciousness of becoming yourself; Tara Westover's memoir *Educated* has that same aching specificity of a young woman claiming her own identity." (Both general-audience, both warm/melancholy.)
4. GOOD example: "*Inside Out* (family animation about childhood emotions) pairs with the picture book *The Color Monster* — both give kids concrete metaphors for feelings they can't yet name." (Both family.)
5. BAD example: "*Inside Out* → *Fleabag*. Both explore raw emotional honesty." — WRONG. Inside Out is a family film; Fleabag is adult tragicomedy with sex and grief. Audience/tone mismatch. This is the kind of suggestion to never make.
6. BAD example: "Both are about young women." — surface-level, no real connection.
7. BAD example: Recommending a thriller because the current item has a "mystery" tag — keyword match, not thematic.
8. If you can't find a strong match that also respects audience/tone, return fewer items rather than reaching.

ADAPTATION: If the current item has a direct adaptation in another medium, include it.

Return ONLY valid JSON, no markdown:
{{
  "adaptation": {{"title": "...", "creator": "author/director name", "media_type": "movie|tv|book", "year": 2020, "note": "one sentence about the adaptation"}} OR null if no direct adaptation,
  "related": {{
    {', '.join([f'"{t}": [{{"title": "...", "year": 2020, "reason": "specific thematic/idea connection citing a concrete element from the current item AND confirming audience/tone match"}}]' for t in other_types])}
  }}
}}"""

        text = (await generate(prompt)).strip()
        if not text:
            log.error("related_items: Gemini returned empty text for %s/%s", media_type, external_id)
            return {"related": {}, "adaptation": None}
        # Robust JSON extraction — strip markdown fences and grab the
        # first balanced {...} block so a wrapped response still parses.
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace : last_brace + 1]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as je:
            log.error(
                "related_items JSON parse failed for %s/%s: %s — snippet: %s",
                media_type, external_id, str(je), text[:400],
            )
            return {"related": {}, "adaptation": None}

        # Enrich related items with posters via parallel search
        async def enrich(rel_item, rel_type):
            title = rel_item.get("title", "")
            creator = rel_item.get("creator") or rel_item.get("author") or ""
            matches = []
            if creator:
                try:
                    matches = await unified_search(f"{title} {creator}", rel_type)
                except Exception:
                    pass
            if not matches:
                try:
                    matches = await unified_search(title, rel_type)
                except Exception:
                    matches = []
            matches = _rank_by_title_match(title, matches, prefer_type=rel_type)
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

        # Pre-filter: drop any AI pick whose raw title is in the user's
        # recent-recs log before we spend API calls on enrichment.
        recent_set = set(recent_recs)
        enriched_related = {}
        tasks = []
        task_types = []
        for rel_type, items in parsed.get("related", {}).items():
            if not isinstance(items, list):
                continue
            for rel_item in items[:2]:
                raw_title = (rel_item.get("title") or "").lower().strip()
                if raw_title and raw_title in recent_set:
                    log.info("related_items: dropping repeat '%s' for user %d", raw_title, user.id)
                    continue
                tasks.append(enrich(rel_item, rel_type))
                task_types.append(rel_type)

        results = await asyncio.gather(*tasks) if tasks else []
        # Post-filter: check the canonical enriched title too, since the
        # search can map a loose AI title to a canonical one the user
        # already saw.
        surfaced_titles: list[str] = []
        for rel_type, result in zip(task_types, results):
            canonical = (result.get("title") or "").lower().strip()
            if canonical and canonical in recent_set:
                log.info("related_items: dropping canonical repeat '%s' for user %d", canonical, user.id)
                continue
            enriched_related.setdefault(rel_type, []).append(result)
            if canonical:
                surfaced_titles.append(canonical)

        # Record this round of recommendations so the next related_items
        # call for a different item can diversify.
        if surfaced_titles:
            cache.add_recent_recs(user.id, surfaced_titles)

        # Enrich adaptation if present — include creator for accuracy
        adaptation = parsed.get("adaptation")
        if adaptation and adaptation.get("title"):
            try:
                ad_title = adaptation["title"]
                ad_creator = adaptation.get("creator") or adaptation.get("author") or ""
                ad_mt = adaptation.get("media_type")
                ad_matches = []
                if ad_creator:
                    try:
                        ad_matches = await unified_search(f"{ad_title} {ad_creator}", ad_mt)
                    except Exception:
                        pass
                if not ad_matches:
                    ad_matches = await unified_search(ad_title, ad_mt)
                ad_matches = _rank_by_title_match(ad_title, ad_matches, prefer_type=ad_mt)
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
        log.info(
            "related_items [%s/%s/user=%d]: %d sections, %d total items, adaptation=%s",
            media_type, external_id, user.id,
            len(enriched_related),
            sum(len(v) for v in enriched_related.values()),
            "yes" if adaptation else "no",
        )
        # 30 day TTL — related items for a given title shift only when
        # the user's profile changes, which the cache layer already
        # gates on via the "related_items" prefix.
        cache.set(cache_key, result, ttl_seconds=2592000)
        return result
    except Exception as e:
        log.error("related_items failed: %s", str(e))
        return {"related": {}, "adaptation": None}


@router.get("/providers/{media_type}/{tmdb_id}")
async def get_providers(media_type: str, tmdb_id: str, user: User = Depends(require_user)):
    """Get streaming providers for a movie/TV item with tier info."""
    from app.services.tmdb import get_watch_providers
    return await get_watch_providers(media_type, tmdb_id)


@router.get("/signature-shelf")
async def get_signature_shelf(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get the user's custom signature shelf, or auto-generate from top-rated items."""
    import json
    from app.models import UserPreferences

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    custom_ids = None
    if prefs and prefs.quiz_results:
        try:
            data = json.loads(prefs.quiz_results)
            custom_ids = data.get("signature_shelf")
        except Exception:
            pass

    if custom_ids:
        # Load custom shelf items by ID
        items = []
        for eid in custom_ids:
            entry = db.query(MediaEntry).filter(MediaEntry.id == eid, MediaEntry.user_id == user.id).first()
            if entry:
                items.append({
                    "id": entry.id, "title": entry.title, "media_type": entry.media_type,
                    "image_url": entry.image_url, "year": entry.year, "rating": entry.rating,
                    "external_id": entry.external_id, "source": entry.source,
                })
        return {"items": items, "is_custom": True}

    # Auto-generate from top-rated items across types
    items = []
    for mt in ["movie", "tv", "book", "podcast"]:
        entries = (
            db.query(MediaEntry)
            .filter(MediaEntry.user_id == user.id, MediaEntry.media_type == mt, MediaEntry.rating.isnot(None))
            .order_by(MediaEntry.rating.desc(), MediaEntry.updated_at.desc())
            .limit(2)
            .all()
        )
        for e in entries:
            items.append({
                "id": e.id, "title": e.title, "media_type": e.media_type,
                "image_url": e.image_url, "year": e.year, "rating": e.rating,
                "external_id": e.external_id, "source": e.source,
            })
    # Sort by rating desc, cap at 5
    items.sort(key=lambda x: -(x.get("rating") or 0))
    return {"items": items[:5], "is_custom": False}


@router.post("/signature-shelf")
async def save_signature_shelf(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Save custom signature shelf item IDs."""
    import json
    from app.models import UserPreferences
    from app import cache

    body = await request.json()
    item_ids = body.get("item_ids", [])[:8]  # max 8

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user.id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user.id)
        db.add(prefs)

    try:
        data = json.loads(prefs.quiz_results) if prefs.quiz_results else {}
    except Exception:
        data = {}

    data["signature_shelf"] = item_ids
    prefs.quiz_results = json.dumps(data)
    db.commit()

    # Bust taste DNA cache so re-analysis uses new signatures
    cache.invalidate(f"taste_dna:{user.id}")

    return {"ok": True}


@router.get("/signal-strength")
async def signal_strength(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Return the user's current signal strength level and nudge."""
    from app.services.signal_strength import calculate_signal
    return calculate_signal(db, user.id)


@router.get("/taste-dna/share-image")
async def taste_dna_share_image(
    request: Request,
    user_id: int | None = None,
    refresh: bool = False,
    layout: str = "portrait",
    db: Session = Depends(get_db),
):
    """Generate a shareable PNG image. Public when user_id is provided
    (so Facebook/Twitter crawlers can fetch it for OG previews)."""
    from fastapi.responses import Response

    from app import cache
    from app.auth import get_current_user

    # Resolve target user: explicit user_id param OR logged-in session
    target_user_id = user_id
    if not target_user_id:
        current = get_current_user(request, db)
        if current:
            target_user_id = current.id
    if not target_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    import base64

    # Check if we have a cached image already
    img_cache_key = f"share_image:{target_user_id}:{layout}"
    if refresh:
        cache.invalidate(img_cache_key)
    cached_img = cache.get(img_cache_key) if not refresh else None
    if cached_img:
        png_bytes = base64.b64decode(cached_img)
        return Response(content=png_bytes, media_type="image/png",
                        headers={"Content-Disposition": "inline; filename=taste-dna.png",
                                 "Cache-Control": "public, max-age=86400"})

    # Generate from taste DNA data
    dna_key = f"taste_dna:{target_user_id}"
    data = cache.get(dna_key)
    if not data or not data.get("themes"):
        raise HTTPException(status_code=404, detail="No taste DNA data — visit My Taste first")

    themes = []
    for t in (data.get("themes") or [])[:3]:
        if isinstance(t, str):
            themes.append(t)
        elif isinstance(t, dict):
            themes.append(t.get("label") or t.get("name") or "")

    # Use the signature shelf for share card posters — same items the user
    # sees on their taste page. Falls back to top-rated if no shelf set.
    import json as _json
    from app.models import UserPreferences as _UP
    poster_urls = []
    _prefs = db.query(_UP).filter(_UP.user_id == target_user_id).first()
    shelf_ids = None
    if _prefs and _prefs.quiz_results:
        try:
            shelf_ids = _json.loads(_prefs.quiz_results).get("signature_shelf")
        except Exception:
            pass
    if shelf_ids:
        for eid in shelf_ids[:6]:
            entry = db.query(MediaEntry).filter(MediaEntry.id == eid).first()
            if entry and entry.image_url:
                poster_urls.append(entry.image_url)
    if not poster_urls:
        # Fallback: top-rated with covers
        top = (
            db.query(MediaEntry.image_url)
            .filter(MediaEntry.user_id == target_user_id, MediaEntry.image_url.isnot(None), MediaEntry.rating >= 4)
            .order_by(MediaEntry.rating.desc())
            .limit(6)
            .all()
        )
        poster_urls = [r.image_url for r in top if r.image_url][:6]

    from app.services.share_card import generate_share_card
    png_bytes = generate_share_card(
        user_name=target_user.name or "Anonymous",
        summary=data.get("summary", ""),
        themes=themes,
        signature_items=(data.get("signature_items") or [])[:5],
        poster_urls=poster_urls,
        layout=layout if layout in ("portrait", "landscape") else "portrait",
    )

    # Cache the generated image (base64) for 7 days so OG crawlers can fetch it
    cache.set(img_cache_key, base64.b64encode(png_bytes).decode(), ttl_seconds=604800)

    return Response(content=png_bytes, media_type="image/png",
                    headers={"Content-Disposition": "inline; filename=taste-dna.png",
                             "Cache-Control": "public, max-age=86400"})


@router.post("/onboarding/mini-quiz")
async def generate_mini_quiz(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Generate 8-10 contextual titles based on the user's 3 favorites.
    Returns items the user likely knows so they can rate quickly."""
    import json

    from app.config import settings
    from app.services.gemini import generate
    from app.services.unified_search import unified_search

    body = await request.json()
    favorites = body.get("favorites", [])
    if not favorites:
        return {"items": []}

    fav_text = "\n".join(f"- {f['title']} ({f.get('media_type', 'unknown')})" for f in favorites[:3])

    # Count media types from favorites to weight the quiz
    type_counts = {}
    for f in favorites[:3]:
        mt = f.get('media_type', 'movie')
        type_counts[mt] = type_counts.get(mt, 0) + 1

    # Build weighting instruction
    if len(type_counts) == 1:
        primary_type = list(type_counts.keys())[0]
        type_instruction = f"At least 7 of the 10 should be {primary_type}s. The rest can be other types the same audience would know."
    elif len(type_counts) == 2:
        types = list(type_counts.keys())
        type_instruction = f"Split roughly evenly between {types[0]}s and {types[1]}s (4-5 each), with 1-2 from other types."
    else:
        type_instruction = "Mix across the same media types the user picked."

    # Age-appropriate content guidance
    from app.services.taste_quiz_scoring import load_age_range
    age_range = load_age_range(db, user.id)
    if age_range == "under_18":
        age_instruction = "CRITICAL AGE RESTRICTION: This user is UNDER 18. You MUST only suggest content rated PG, PG-13, or TV-14 and below. NEVER suggest R-rated movies, TV-MA shows, or content with explicit sex, heavy drug use, or graphic violence. Specifically DO NOT suggest: Euphoria, Game of Thrones, Breaking Bad, Squid Game, or similar TV-MA content. Focus on titles from 2010-present that a teenager would actually be allowed to watch/read — across movies, TV, books, and podcasts."
    elif age_range == "18_35":
        age_instruction = "This user is 18-35. They likely know a mix of 2000s-present content across all media types. Include both mainstream hits and well-known indie/cult favorites."
    elif age_range == "35_50":
        age_instruction = "This user is 35-50. They have deep knowledge of 90s-2010s content and likely appreciate both popular and critically acclaimed titles across movies, TV, books, and podcasts. Include titles from across the last 30 years."
    elif age_range == "over_50":
        age_instruction = "This user is over 50. Include well-known titles from the 70s-2000s they'd know well, alongside newer content. Don't assume they only watch old stuff — but don't assume they've seen every recent streaming original either. Respect the depth of their experience across movies, TV, books, and podcasts."
    else:
        age_instruction = ""

    prompt = f"""Based on these 3 favorites, suggest 10 titles the user has VERY LIKELY already seen/read/listened to. Pick things in the same orbit — similar audiences, similar vibes, same era — that most fans of these titles would know.
{age_instruction}

User's favorites:
{fav_text}

{type_instruction} Each item should be well-known enough that 70%+ of fans of the favorites would recognize it.

Return ONLY valid JSON — a list of objects with "title", "media_type" (movie/tv/book/podcast), "year", and "creator" (director, author, or host). No markdown.

[{{"title": "...", "media_type": "movie", "year": 2020, "creator": "Director Name"}}, ...]"""

    try:
        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        first_bracket = text.find("[")
        last_bracket = text.rfind("]")
        if first_bracket >= 0 and last_bracket > first_bracket:
            text = text[first_bracket:last_bracket + 1]
        raw_items = json.loads(text)
    except Exception as e:
        log.error("mini-quiz generation failed: %s", str(e))
        return {"items": []}

    # Enrich with posters via search — include creator for precision
    enriched = []
    for item in raw_items[:10]:
        title = item.get("title", "")
        creator = item.get("creator", "")
        mt = item.get("media_type")
        try:
            # Search with title + creator first, fall back to title only
            query = f"{title} {creator}" if creator else title
            matches = await unified_search(query, mt)
            if not matches and creator:
                matches = await unified_search(title, mt)
            matches = _rank_by_title_match(title, matches)
            # Reject matches where the title is wildly different (WHO textbook for "The Selection")
            if matches:
                best_title = matches[0].title.lower()
                orig_title = title.lower()
                # Accept if the original title is contained in the match or vice versa
                if orig_title not in best_title and best_title not in orig_title:
                    # Check word overlap — at least 50% of words should match
                    orig_words = set(orig_title.split())
                    best_words = set(best_title.split())
                    overlap = len(orig_words & best_words)
                    if overlap < len(orig_words) * 0.5:
                        matches = []  # reject — too different
            if matches:
                best = matches[0]
                enriched.append({
                    "title": best.title,
                    "media_type": best.media_type,
                    "year": best.year,
                    "image_url": best.image_url,
                    "external_id": best.external_id,
                    "source": best.source,
                    "creator": best.creator,
                    "genres": best.genres,
                    "description": best.description,
                })
            else:
                enriched.append({
                    "title": title, "media_type": mt or "movie",
                    "year": item.get("year"), "image_url": None,
                    "external_id": "", "source": "", "creator": None,
                    "genres": [], "description": None,
                })
        except Exception:
            enriched.append({
                "title": title, "media_type": mt or "movie",
                "year": item.get("year"), "image_url": None,
                "external_id": "", "source": "", "creator": None,
                "genres": [], "description": None,
            })

    return {"items": enriched}


@router.get("/what-youre-missing")
async def what_youre_missing(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Find great taste matches on services the user doesn't subscribe to."""
    import json

    from app import cache
    from app.config import settings
    from app.models import MediaEntry
    from app.services.taste_quiz_scoring import load_streaming_services
    from app.services.tmdb import TIER1_PROVIDERS

    user_services = load_streaming_services(db, user.id)
    if not user_services or not settings.gemini_api_key:
        return []

    cache_key = f"missing:{user.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Build taste summary
    top_rated = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None))
        .order_by(MediaEntry.rating.desc())
        .limit(15)
        .all()
    )
    if len(top_rated) < 5:
        return []

    taste_lines = [f"- {e.title} ({e.media_type}, {e.rating}/5)" for e in top_rated]

    user_service_names = [TIER1_PROVIDERS.get(pid, "") for pid in user_services if pid in TIER1_PROVIDERS]
    other_services = {pid: name for pid, name in TIER1_PROVIDERS.items() if pid not in user_services and pid not in (38, 103, 380, 21, 385)}
    other_service_names = list(other_services.values())

    if not other_service_names:
        return []

    from app.services.gemini import generate

    prompt = f"""You are finding movies and TV shows that are great fits for this user's taste but are ONLY available on services they DON'T currently subscribe to.

USER'S TASTE (top-rated items):
{chr(10).join(taste_lines)}

SERVICES THEY HAVE: {', '.join(user_service_names)}
SERVICES THEY DON'T HAVE: {', '.join(other_service_names)}

Find 4 movies or TV shows that:
1. Are a strong taste match (would rate 4+ based on their profile)
2. Are available ONLY on services they DON'T have (not on any of their current services)
3. Are well-known enough to be a genuine draw

For each, specify which service it's on.

Return ONLY valid JSON — a list of objects:
[{{"title": "...", "media_type": "movie|tv", "year": 2020, "available_on": "Service Name", "reason": "One sentence why this fits their taste"}}]
"""

    try:
        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        first = text.find("[")
        last = text.rfind("]")
        if first >= 0 and last > first:
            text = text[first:last + 1]
        items = json.loads(text)

        # Enrich with posters
        from app.services.unified_search import unified_search
        enriched = []
        for item in items[:4]:
            title = item.get("title", "")
            mt = item.get("media_type", "movie")
            try:
                results = await unified_search(f"{title}", mt)
                if results:
                    best = results[0]
                    enriched.append({
                        "title": best.title,
                        "media_type": best.media_type,
                        "year": best.year,
                        "image_url": best.image_url,
                        "external_id": best.external_id,
                        "source": best.source,
                        "available_on": item.get("available_on", ""),
                        "reason": item.get("reason", ""),
                    })
            except Exception:
                enriched.append({
                    "title": title, "media_type": mt,
                    "year": item.get("year"),
                    "image_url": None, "external_id": "", "source": "",
                    "available_on": item.get("available_on", ""),
                    "reason": item.get("reason", ""),
                })

        cache.set(cache_key, enriched, ttl_seconds=604800)  # 7 days
        return enriched
    except Exception as e:
        log.error("what-youre-missing failed: %s", str(e))
        return []


@router.get("/taste-fit/{media_type}/{external_id}")
async def taste_fit(
    media_type: str, external_id: str,
    title: str = Query(""), source: str = Query(""),
    description: str = Query(""), creator: str = Query(""), genres: str = Query(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Quick AI prediction: how well does this item fit the user's taste?"""
    import json

    from app import cache
    from app.config import settings
    from app.models import MediaEntry

    # If this item is already in the user's profile with a predicted_rating,
    # use that instead of generating a new (potentially conflicting) one.
    existing = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id,
        MediaEntry.external_id == external_id,
    ).first()
    if existing and existing.predicted_rating:
        return {"predicted_rating": existing.predicted_rating, "reason": None}

    cache_key = f"taste_fit:{user.id}:{media_type}:{external_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if not settings.gemini_api_key or not title:
        return {"predicted_rating": None, "reason": None}

    top_rated = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None))
        .order_by(MediaEntry.rating.desc())
        .limit(15)
        .all()
    )
    low_rated = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None), MediaEntry.rating <= 2)
        .order_by(MediaEntry.rating.asc())
        .limit(10)
        .all()
    )

    loved = "\n".join(f"- {e.title} ({e.media_type}, {e.rating}/5) [{e.genres or ''}]" for e in top_rated) or "no data"
    disliked = "\n".join(f"- {e.title} ({e.media_type}, {e.rating}/5) [{e.genres or ''}]" for e in low_rated) or "none"

    from app.services.gemini import generate

    prompt = f"""Predict how much this user would enjoy a specific item on a 1-5 scale, and explain why in one sentence.

ITEMS THEY LOVED (rated 4-5):
{loved}

ITEMS THEY DISLIKED (rated 1-2):
{disliked}

ITEM TO EVALUATE:
Title: {title}
Type: {media_type}
{f'By: {creator}' if creator else ''}
{f'Genres: {genres}' if genres else ''}
{f'Description: {description}' if description else ''}

RULES:
- Be honest, not generous. Most items are a 3-3.5 for any given person. Only give 4+ for genuine taste matches.
- If the item's genre/tone/style resembles their disliked items, score it 1.5-2.5.
- If you don't recognize the item or can't tell, return null.
- A 5.0 means near-perfect match to their absolute favorites. Extremely rare.
- The reason should cite a specific item from their profile and name a concrete connection.

Return ONLY a JSON object:
{{"predicted_rating": 3.2, "reason": "Your mixed feelings about similar memoirs suggest this would be pleasant but not a standout."}}
"""
    try:
        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]
        parsed = json.loads(text)
        result = {
            "predicted_rating": parsed.get("predicted_rating"),
            "reason": parsed.get("reason"),
        }
    except Exception as e:
        log.error("taste_fit failed: %s", str(e))
        result = {"predicted_rating": None, "reason": None}

    cache.set(cache_key, result, ttl_seconds=604800)
    return result


@router.get("/{media_type}/{external_id}")
async def get_media_detail(media_type: str, external_id: str, source: str = ""):
    """Get detailed info for a specific media item."""
    from app.services.unified_search import get_detail

    result = await get_detail(media_type, external_id, source)
    if result is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return result
