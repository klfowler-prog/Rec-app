"""Google Books API client — used as a fallback when Open Library is down."""

import httpx

from app.config import settings
from app.schemas import MediaResult

BASE_URL = "https://www.googleapis.com/books/v1/volumes"


async def search(query: str) -> list[MediaResult]:
    """Search Google Books. Returns MediaResult with source='google_books'
    and external_id set to the Open Library work ID when we can resolve
    one, falling back to the Google Books volume ID."""
    params: dict = {"q": query, "maxResults": 10, "printType": "books"}
    api_key = settings.google_books_api_key or settings.gemini_api_key
    if api_key:
        params["key"] = api_key

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    results: list[MediaResult] = []
    for item in data.get("items", []):
        info = item.get("volumeInfo", {})
        title = info.get("title", "")
        if not title:
            continue

        authors = info.get("authors", [])
        categories = info.get("categories", [])[:5]
        year = None
        pub_date = info.get("publishedDate", "")
        if pub_date:
            try:
                year = int(pub_date[:4])
            except (ValueError, IndexError):
                pass

        # Prefer ISBN-13 for cover and ID resolution
        isbns = info.get("industryIdentifiers", [])
        isbn13 = next((i["identifier"] for i in isbns if i.get("type") == "ISBN_13"), None)
        isbn10 = next((i["identifier"] for i in isbns if i.get("type") == "ISBN_10"), None)
        isbn = isbn13 or isbn10

        # Google Books thumbnail
        image_url = info.get("imageLinks", {}).get("thumbnail")
        # Upgrade to https
        if image_url and image_url.startswith("http://"):
            image_url = image_url.replace("http://", "https://")

        # Use Google volume ID as external_id, source as google_books.
        # The detail page will still work via get_details below.
        volume_id = item.get("id", "")

        results.append(MediaResult(
            external_id=volume_id,
            source="google_books",
            media_type="book",
            title=title,
            image_url=image_url,
            year=year,
            creator=", ".join(authors[:2]) if authors else None,
            genres=categories,
            description=info.get("description"),
            external_url=info.get("canonicalVolumeLink"),
        ))

    return results


async def get_details(volume_id: str) -> MediaResult | None:
    """Fetch details for a single Google Books volume."""
    params: dict = {}
    api_key = settings.google_books_api_key or settings.gemini_api_key
    if api_key:
        params["key"] = api_key

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{BASE_URL}/{volume_id}", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        item = resp.json()

    info = item.get("volumeInfo", {})
    title = info.get("title", "")
    authors = info.get("authors", [])
    categories = info.get("categories", [])[:8]

    year = None
    pub_date = info.get("publishedDate", "")
    if pub_date:
        try:
            year = int(pub_date[:4])
        except (ValueError, IndexError):
            pass

    image_url = info.get("imageLinks", {}).get("thumbnail")
    if image_url and image_url.startswith("http://"):
        image_url = image_url.replace("http://", "https://")

    return MediaResult(
        external_id=volume_id,
        source="google_books",
        media_type="book",
        title=title,
        image_url=image_url,
        year=year,
        creator=", ".join(authors[:2]) if authors else None,
        genres=categories,
        description=info.get("description"),
        external_url=info.get("canonicalVolumeLink"),
    )
