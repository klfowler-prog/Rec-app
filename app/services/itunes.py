import httpx

from app.schemas import MediaResult

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"


async def search(query: str) -> list[MediaResult]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            SEARCH_URL,
            params={"term": query, "entity": "podcast", "limit": 10},
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("results", []):
        date = item.get("releaseDate", "")
        year = int(date[:4]) if date and len(date) >= 4 else None

        genres = [item.get("primaryGenreName")] if item.get("primaryGenreName") else []

        results.append(
            MediaResult(
                external_id=str(item.get("collectionId", item.get("trackId", ""))),
                source="itunes",
                media_type="podcast",
                title=item.get("collectionName", item.get("trackName", "")),
                image_url=item.get("artworkUrl600") or item.get("artworkUrl100"),
                year=year,
                creator=item.get("artistName"),
                genres=genres,
                description=None,
                external_url=item.get("collectionViewUrl") or item.get("trackViewUrl"),
            )
        )
    return results


async def get_details(collection_id: str) -> MediaResult | None:
    """Get podcast details by collection ID using iTunes lookup API."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(LOOKUP_URL, params={"id": collection_id})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    if not results:
        return None

    item = results[0]
    date = item.get("releaseDate", "")
    year = int(date[:4]) if date and len(date) >= 4 else None
    genres = [item.get("primaryGenreName")] if item.get("primaryGenreName") else []
    description = item.get("description") or item.get("collectionDescription") or None

    return MediaResult(
        external_id=str(item.get("collectionId", item.get("trackId", ""))),
        source="itunes",
        media_type="podcast",
        title=item.get("collectionName", item.get("trackName", "")),
        image_url=item.get("artworkUrl600") or item.get("artworkUrl100"),
        year=year,
        creator=item.get("artistName"),
        genres=genres,
        description=description,
        external_url=item.get("collectionViewUrl") or item.get("trackViewUrl"),
    )
