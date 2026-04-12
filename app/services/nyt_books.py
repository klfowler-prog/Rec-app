"""NYT Books API client for curated bestseller lists.

Used by the per-type /profile/books "What's new" section. NYT gives us
a weekly-curated list of real trade-published books, which is much
cleaner than Open Library's sort=rating (which surfaces self-published
slop and AI-generated spam).

Requires NYT_API_KEY in the environment. If missing, returns an empty
list and the caller should fall back.
"""

import asyncio
import logging

import httpx

from app.config import settings
from app.schemas import MediaResult

log = logging.getLogger(__name__)

BASE_URL = "https://api.nytimes.com/svc/books/v3"


async def _fetch_list(list_name: str, limit: int = 15) -> list[dict]:
    """Fetch a single bestseller list by slug (e.g. 'hardcover-fiction').
    Returns raw NYT book dicts — the caller normalizes to MediaResult."""
    if not settings.nyt_api_key:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/lists/current/{list_name}.json",
            params={"api-key": settings.nyt_api_key},
        )
        if resp.status_code != 200:
            log.error("NYT %s list fetch failed: %s %s", list_name, resp.status_code, resp.text[:200])
            return []
        data = resp.json()
    books = data.get("results", {}).get("books", [])
    return books[:limit]


async def _resolve_openlibrary_work_id(title: str, author: str) -> tuple[str | None, int | None]:
    """Look up an Open Library work_id for a (title, author) pair so the
    detail page can render the full book view. Returns (work_id, year)
    or (None, None) if nothing matches.

    NYT doesn't hand us Open Library IDs, so we do a best-effort
    lookup. Failures are silent — the card still works, it just links
    to a fallback."""
    query = f"{title} {author}".strip() if author else title
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://openlibrary.org/search.json",
                params={
                    "q": query,
                    "limit": 3,
                    "fields": "key,title,author_name,first_publish_year",
                },
            )
            if resp.status_code != 200:
                return None, None
            data = resp.json()
    except Exception:
        return None, None

    docs = data.get("docs", [])
    title_lower = (title or "").lower().strip()
    for doc in docs:
        doc_title = (doc.get("title") or "").lower().strip()
        # Accept an exact or near-exact match on the title. The author
        # is fuzzy across OL editions so we don't over-constrain on it.
        if doc_title == title_lower or title_lower.startswith(doc_title) or doc_title.startswith(title_lower):
            work_key = doc.get("key", "")
            work_id = work_key.replace("/works/", "") if work_key else None
            return work_id, doc.get("first_publish_year")
    # Fall back to the first result
    if docs:
        work_key = docs[0].get("key", "")
        work_id = work_key.replace("/works/", "") if work_key else None
        return work_id, docs[0].get("first_publish_year")
    return None, None


async def get_bestsellers(limit_per_list: int = 10) -> list[tuple[str, list[MediaResult]]]:
    """Return a list of (section_label, books) tuples covering fiction
    and nonfiction NYT bestseller lists. Each book is enriched with an
    Open Library work_id (via a parallel lookup) so detail pages work.

    Returns an empty list if NYT_API_KEY is missing — caller should
    fall back to a different source."""
    if not settings.nyt_api_key:
        return []

    # Fetch both lists in parallel
    fiction_raw, nonfiction_raw = await asyncio.gather(
        _fetch_list("hardcover-fiction", limit=limit_per_list),
        _fetch_list("hardcover-nonfiction", limit=limit_per_list),
    )

    if not fiction_raw and not nonfiction_raw:
        return []

    # Collect every (title, author) we need to resolve and dedupe, then
    # run all lookups in parallel. Each lookup is ~300ms.
    lookup_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for b in fiction_raw + nonfiction_raw:
        pair = (b.get("title", ""), b.get("author", ""))
        if pair not in seen_pairs:
            lookup_pairs.append(pair)
            seen_pairs.add(pair)

    lookup_results = await asyncio.gather(
        *[_resolve_openlibrary_work_id(t, a) for t, a in lookup_pairs]
    )
    lookup_map: dict[tuple[str, str], tuple[str | None, int | None]] = {
        pair: result for pair, result in zip(lookup_pairs, lookup_results)
    }

    def _to_media_result(b: dict) -> MediaResult:
        title = b.get("title", "").strip()
        # NYT titles arrive UPPERCASE — titlecase looks much nicer in cards.
        if title.isupper():
            title = title.title()
        author = b.get("author", "")
        work_id, year = lookup_map.get((b.get("title", ""), author), (None, None))
        # Use the Open Library work_id if we found one, otherwise fall
        # back to the primary ISBN so the item still has a stable ID.
        external_id = work_id or b.get("primary_isbn13") or b.get("primary_isbn10") or title.lower().replace(" ", "-")[:50]
        source = "open_library" if work_id else "nyt"
        return MediaResult(
            external_id=external_id,
            source=source,
            media_type="book",
            title=title,
            image_url=b.get("book_image") or None,
            year=year,
            creator=author or None,
            genres=[],  # NYT lists don't carry genres; we rely on title + description for scoring
            description=b.get("description") or None,
            external_url=b.get("amazon_product_url") or None,
        )

    sections: list[tuple[str, list[MediaResult]]] = []
    if fiction_raw:
        sections.append(("NYT Fiction Bestsellers", [_to_media_result(b) for b in fiction_raw]))
    if nonfiction_raw:
        sections.append(("NYT Nonfiction Bestsellers", [_to_media_result(b) for b in nonfiction_raw]))
    return sections
