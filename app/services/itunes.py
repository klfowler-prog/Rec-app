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


async def get_top_podcasts(limit: int = 25) -> list[MediaResult]:
    """Fetch the current top podcasts from the iTunes Generator RSS feed.
    Used as a 'what's new/hot in podcasts' source for the per-type
    profile page."""
    url = f"https://itunes.apple.com/us/rss/toppodcasts/limit={limit}/json"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return []
        data = resp.json()

    feed = data.get("feed", {})
    entries = feed.get("entry", [])
    results = []
    for item in entries:
        title = (item.get("im:name") or {}).get("label", "")
        artist = (item.get("im:artist") or {}).get("label")
        # Pick the largest image
        images = item.get("im:image", [])
        image_url = images[-1].get("label") if images else None
        # The iTunes collection ID is in the id attributes
        raw_id = (item.get("id") or {}).get("attributes", {}).get("im:id") or ""
        category = ((item.get("category") or {}).get("attributes") or {}).get("label")
        genres = [category] if category else []
        results.append(
            MediaResult(
                external_id=str(raw_id),
                source="itunes",
                media_type="podcast",
                title=title,
                image_url=image_url,
                year=None,
                creator=artist,
                genres=genres,
                description=None,
                external_url=(item.get("link") or {}).get("attributes", {}).get("href") if isinstance(item.get("link"), dict) else None,
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

    # iTunes lookup rarely includes descriptions for podcasts.
    # Fall back to the RSS feed which always has one.
    if not description and item.get("feedUrl"):
        try:
            from xml.etree import ElementTree

            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as feed_client:
                feed_resp = await feed_client.get(item["feedUrl"])
                if feed_resp.status_code == 200:
                    root = ElementTree.fromstring(feed_resp.text)
                    channel = root.find("channel")
                    if channel is not None:
                        description = (
                            channel.findtext("{http://www.itunes.com/dtds/podcast-1.0.dtd}summary")
                            or channel.findtext("description")
                        )
        except Exception:
            pass

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
