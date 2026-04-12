import httpx

from app.schemas import MediaResult

BASE_URL = "https://openlibrary.org"


async def search(query: str) -> list[MediaResult]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/search.json",
            params={
                "q": query,
                # Request more results since we'll prefer ones with covers.
                # Many Open Library matches are edition stubs without cover_i.
                "limit": 20,
                "fields": "key,title,author_name,first_publish_year,cover_i,edition_count,subject,isbn",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for doc in data.get("docs", []):
        work_key = doc.get("key", "")
        work_id = work_key.replace("/works/", "") if work_key else ""
        if not work_id:
            continue

        cover_id = doc.get("cover_i")
        image_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None
        authors = doc.get("author_name", [])
        subjects = doc.get("subject", [])[:5]

        results.append(
            (
                bool(cover_id),
                doc.get("edition_count") or 0,
                MediaResult(
                    external_id=work_id,
                    source="open_library",
                    media_type="book",
                    title=doc.get("title", ""),
                    image_url=image_url,
                    year=doc.get("first_publish_year"),
                    creator=", ".join(authors[:2]) if authors else None,
                    genres=subjects,
                    description=None,
                    external_url=f"https://openlibrary.org/works/{work_id}",
                ),
            )
        )

    # Preserve Open Library's relevance order but float results that have
    # a cover image to the top. Break further ties by edition_count
    # (a rough popularity proxy — the real "Great Gatsby" has thousands of
    # editions, the random stub has 1).
    results.sort(key=lambda t: (0 if t[0] else 1, -t[1]))
    return [r[2] for r in results]


async def get_recent_books(limit: int = 20) -> list[MediaResult]:
    """Fetch recent books from Open Library. There's no direct 'new
    releases' endpoint, so we query the search API for the current year
    sorted by popularity. Not as tight as TMDB's now_playing but gives
    us something reasonable to surface as 'what's new in books'."""
    from datetime import datetime
    current_year = datetime.utcnow().year
    # Search for books published in the last two years, sorted by rating
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/search.json",
            params={
                "q": f"first_publish_year:[{current_year - 1} TO {current_year}]",
                "limit": limit * 2,
                "sort": "rating",
                "fields": "key,title,author_name,first_publish_year,cover_i,subject,edition_count",
            },
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    results = []
    for doc in data.get("docs", []):
        work_key = doc.get("key", "")
        work_id = work_key.replace("/works/", "") if work_key else ""
        if not work_id:
            continue
        cover_id = doc.get("cover_i")
        if not cover_id:
            continue  # Skip editions without covers — we want a clean grid
        image_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"
        authors = doc.get("author_name", [])
        subjects = doc.get("subject", [])[:5]
        results.append(
            MediaResult(
                external_id=work_id,
                source="open_library",
                media_type="book",
                title=doc.get("title", ""),
                image_url=image_url,
                year=doc.get("first_publish_year"),
                creator=", ".join(authors[:2]) if authors else None,
                genres=subjects,
                description=None,
                external_url=f"https://openlibrary.org/works/{work_id}",
            )
        )
        if len(results) >= limit:
            break
    return results


async def get_details(work_id: str) -> MediaResult | None:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{BASE_URL}/works/{work_id}.json")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        work = resp.json()

    title = work.get("title", "")

    # Get description
    desc = work.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value", "")
    elif not isinstance(desc, str):
        desc = None

    # Get subjects
    subjects = [s for s in work.get("subjects", [])[:8] if isinstance(s, str)]

    # Get cover
    covers = work.get("covers", [])
    image_url = f"https://covers.openlibrary.org/b/id/{covers[0]}-M.jpg" if covers else None

    # Get authors in parallel
    import asyncio
    author_keys = [a.get("author", {}).get("key", "") for a in work.get("authors", [])[:2]]
    author_names = []
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = [client.get(f"{BASE_URL}{key}.json") for key in author_keys if key]
        if tasks:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            for r in responses:
                if hasattr(r, "status_code") and r.status_code == 200:
                    author_names.append(r.json().get("name", ""))

    year = None
    if work.get("first_publish_date"):
        try:
            year = int(work["first_publish_date"][:4])
        except (ValueError, IndexError):
            pass

    return MediaResult(
        external_id=work_id,
        source="open_library",
        media_type="book",
        title=title,
        image_url=image_url,
        year=year,
        creator=", ".join(author_names) if author_names else None,
        genres=subjects,
        description=desc,
        external_url=f"https://openlibrary.org/works/{work_id}",
    )
