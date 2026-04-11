import httpx

from app.schemas import MediaResult

SEARCH_URL = "https://itunes.apple.com/search"


async def search(query: str) -> list[MediaResult]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            SEARCH_URL,
            params={"term": query, "entity": "podcast", "limit": 10},
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("results", []):
        # Parse release date year
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
