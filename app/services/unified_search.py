import asyncio

from app.schemas import MediaResult
from app.services import itunes, open_library, tmdb


async def unified_search(query: str, media_type: str | None = None) -> list[MediaResult]:
    """Search across all media APIs in parallel, filtered by type if specified."""
    tasks = []

    if media_type in (None, "movie", "tv"):
        tasks.append(tmdb.search(query, media_type))
    if media_type in (None, "book"):
        tasks.append(open_library.search(query))
    if media_type in (None, "podcast"):
        tasks.append(itunes.search(query))

    all_results: list[MediaResult] = []
    settled = await asyncio.gather(*tasks, return_exceptions=True)
    for result in settled:
        if isinstance(result, list):
            all_results.extend(result)
        # Silently skip failed APIs

    return all_results


async def get_detail(media_type: str, external_id: str, source: str) -> MediaResult | None:
    """Get detailed info from the appropriate API."""
    if source == "tmdb" or media_type in ("movie", "tv"):
        return await tmdb.get_details(media_type, external_id)
    elif source == "open_library" or media_type == "book":
        return await open_library.get_details(external_id)
    # Podcasts don't have a detail endpoint in iTunes search — return None
    return None
