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


async def search_books(query: str) -> list[MediaResult]:
    """Search for books across Open Library + Google Books. Tries OL
    first, falls back to GB if OL fails or returns no results with
    covers. This is the single entry point all book-cover-needing
    callers should use instead of importing open_library.search directly."""
    results: list[MediaResult] = []
    try:
        results = await open_library.search(query)
    except Exception:
        pass

    # If OL returned results but none have covers, or OL failed entirely,
    # try Google Books
    has_covers = any(r.image_url for r in results)
    if not has_covers:
        try:
            gb = await google_books.search(query)
            if gb:
                # If OL returned nothing, use GB entirely.
                # If OL returned coverless results, merge GB covers in.
                if not results:
                    results = gb
                else:
                    # Build a map of GB covers by normalized title
                    gb_covers = {}
                    for r in gb:
                        if r.image_url:
                            gb_covers[r.title.lower().strip()] = r.image_url
                    # Patch OL results with GB covers
                    for r in results:
                        if not r.image_url:
                            gb_url = gb_covers.get(r.title.lower().strip())
                            if gb_url:
                                r.image_url = gb_url
                    # Also append any GB results not in OL
                    ol_titles = {r.title.lower().strip() for r in results}
                    for r in gb:
                        if r.title.lower().strip() not in ol_titles:
                            results.append(r)
        except Exception:
            pass

    return results


async def get_detail(media_type: str, external_id: str, source: str) -> MediaResult | None:
    """Get detailed info from the appropriate API."""
    if source == "tmdb" or (media_type in ("movie", "tv") and source not in ("open_library", "google_books", "itunes")):
        return await tmdb.get_details(media_type, external_id)
    elif source == "google_books":
        try:
            return await google_books.get_details(external_id)
        except Exception:
            pass
        return None
    elif source in ("open_library", "nyt") or media_type == "book":
        # If external_id is an ISBN (all digits), search by title instead
        # of treating it as a work ID — OL and GB detail endpoints don't
        # accept ISBNs directly.
        if external_id.isdigit() or (external_id.replace("-", "").isdigit()):
            try:
                results = await search_books(external_id)
                if results:
                    return results[0]
            except Exception:
                pass
            return None
        result = None
        try:
            result = await open_library.get_details(external_id)
        except Exception:
            pass

        # If OL returned nothing or is missing description/cover,
        # try Google Books to fill gaps
        needs_supplement = (
            not result
            or not result.description
            or not result.image_url
        )
        if needs_supplement:
            try:
                # Search GB by title to find a matching volume
                query = result.title if result else external_id
                gb_results = await google_books.search(query)
                if gb_results:
                    gb = gb_results[0]
                    if not result:
                        return gb
                    # Patch missing fields from GB
                    if not result.description and gb.description:
                        result.description = gb.description
                    if not result.image_url and gb.image_url:
                        result.image_url = gb.image_url
            except Exception:
                pass

        if result:
            return result

        # Last resort: try GB detail by volume ID
        if not external_id.startswith("OL"):
            try:
                return await google_books.get_details(external_id)
            except Exception:
                pass
        return None
    elif source == "itunes" or media_type == "podcast":
        return await itunes.get_details(external_id)
    return None
