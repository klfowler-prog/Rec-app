import asyncio

from app.schemas import MediaResult
from app.services import google_books, itunes, open_library, tmdb


async def unified_search(query: str, media_type: str | None = None) -> list[MediaResult]:
    """Search across all media APIs in parallel, filtered by type if specified.

    For books, tries Open Library first. If it fails, falls back to
    Google Books so searches still work when Internet Archive is down.
    """
    tasks = []
    task_labels = []

    if media_type in (None, "movie", "tv"):
        tasks.append(tmdb.search(query, media_type))
        task_labels.append("tmdb")
    if media_type in (None, "book"):
        tasks.append(open_library.search(query))
        task_labels.append("open_library")
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
            if label == "open_library":
                book_failed = True

    # If Open Library failed, try Google Books as fallback
    if book_failed:
        try:
            gb_results = await google_books.search(query)
            if gb_results:
                all_results.extend(gb_results)
                errors -= 1  # recovered
        except Exception:
            pass  # both book APIs down

    # If every API failed, raise so callers can distinguish "no results"
    # from "couldn't reach the service at all".
    if errors == len(settled) and errors > 0:
        raise RuntimeError("All search APIs failed")

    return all_results


async def get_detail(media_type: str, external_id: str, source: str) -> MediaResult | None:
    """Get detailed info from the appropriate API."""
    if source == "tmdb" or (media_type in ("movie", "tv") and source not in ("open_library", "google_books", "itunes")):
        return await tmdb.get_details(media_type, external_id)
    elif source == "google_books":
        return await google_books.get_details(external_id)
    elif source == "open_library" or media_type == "book":
        try:
            result = await open_library.get_details(external_id)
            if result:
                return result
        except Exception:
            pass
        # Fallback: if external_id looks like a Google Books volume ID
        # (not an OL work key), try Google Books
        if not external_id.startswith("OL"):
            try:
                return await google_books.get_details(external_id)
            except Exception:
                pass
        return None
    elif source == "itunes" or media_type == "podcast":
        return await itunes.get_details(external_id)
    return None
