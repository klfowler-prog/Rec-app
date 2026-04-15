"""Unified search and detail resolution across all media APIs.

Book search order: Google Books first (reliable covers + descriptions),
Open Library as supplement. This was flipped in April 2026 after months
of OL cover failures, missing descriptions, and Internet Archive outages.
"""

import asyncio

from app.schemas import MediaResult
from app.services import google_books, itunes, open_library, tmdb


async def unified_search(query: str, media_type: str | None = None) -> list[MediaResult]:
    """Search across all media APIs in parallel, filtered by type."""
    tasks = []
    task_labels = []

    if media_type in (None, "movie", "tv"):
        tasks.append(tmdb.search(query, media_type))
        task_labels.append("tmdb")
    if media_type in (None, "book"):
        tasks.append(google_books.search(query))
        task_labels.append("google_books")
    if media_type in (None, "podcast"):
        tasks.append(itunes.search(query))
        task_labels.append("itunes")

    all_results: list[MediaResult] = []
    errors = 0
    book_failed = False
    settled = await asyncio.gather(*tasks, return_exceptions=True)
    for label, result in zip(task_labels, settled):
        if isinstance(result, list):
            all_results.extend(result)
        else:
            errors += 1
            if label == "google_books":
                book_failed = True

    # If Google Books failed, try Open Library as fallback
    if book_failed:
        try:
            ol_results = await open_library.search(query)
            if ol_results:
                all_results.extend(ol_results)
                errors -= 1
        except Exception:
            pass

    if errors == len(settled) and errors > 0:
        raise RuntimeError("All search APIs failed")

    return all_results


async def search_books(query: str) -> list[MediaResult]:
    """Search for books — Google Books primary, Open Library fallback.
    Single entry point for all book-search callers across the app."""
    results: list[MediaResult] = []
    try:
        results = await google_books.search(query)
    except Exception:
        pass

    # If GB returned nothing, try OL
    if not results:
        try:
            results = await open_library.search(query)
        except Exception:
            pass

    return results


async def get_detail(media_type: str, external_id: str, source: str) -> MediaResult | None:
    """Get detailed info from the appropriate API."""
    if source == "tmdb" or (media_type in ("movie", "tv") and source not in ("open_library", "google_books", "itunes", "nyt")):
        return await tmdb.get_details(media_type, external_id)

    elif source == "google_books":
        try:
            return await google_books.get_details(external_id)
        except Exception:
            pass
        return None

    elif source in ("open_library", "nyt") or media_type == "book":
        # ISBN-based IDs: search by ISBN since detail APIs don't accept them
        if external_id.isdigit() or external_id.replace("-", "").isdigit():
            try:
                results = await search_books(external_id)
                if results:
                    return results[0]
            except Exception:
                pass
            return None

        # OL work ID — try OL first for this specific ID
        result = None
        if external_id.startswith("OL"):
            try:
                result = await open_library.get_details(external_id)
            except Exception:
                pass

        # Supplement or replace with Google Books if missing data
        if not result or not result.description or not result.image_url:
            try:
                query = result.title if result else external_id
                gb_results = await google_books.search(query)
                if gb_results:
                    gb = gb_results[0]
                    if not result:
                        return gb
                    if not result.description and gb.description:
                        result.description = gb.description
                    if not result.image_url and gb.image_url:
                        result.image_url = gb.image_url
            except Exception:
                pass

        if result:
            return result

        # Last resort: try as a GB volume ID
        try:
            return await google_books.get_details(external_id)
        except Exception:
            pass
        return None

    elif source == "itunes" or media_type == "podcast":
        return await itunes.get_details(external_id)

    return None
