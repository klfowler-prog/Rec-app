import httpx

from app.config import settings
from app.schemas import MediaResult

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
LOGO_BASE = "https://image.tmdb.org/t/p/w92"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.tmdb_api_key}", "Accept": "application/json"}


async def search(query: str, media_type: str | None = None) -> list[MediaResult]:
    if not settings.tmdb_api_key:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        if media_type == "movie":
            url = f"{BASE_URL}/search/movie"
        elif media_type == "tv":
            url = f"{BASE_URL}/search/tv"
        else:
            url = f"{BASE_URL}/search/multi"
        resp = await client.get(url, headers=_headers(), params={"query": query, "page": 1})
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("results", [])[:10]:
        mt = item.get("media_type", media_type or "movie")
        if mt not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name", "")
        date = item.get("release_date") or item.get("first_air_date", "")
        year = int(date[:4]) if date and len(date) >= 4 else None
        poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
        genre_ids = item.get("genre_ids", [])
        genres = [GENRE_MAP.get(gid, "") for gid in genre_ids]
        genres = [g for g in genres if g]

        results.append(
            MediaResult(
                external_id=str(item["id"]),
                source="tmdb",
                media_type=mt,
                title=title,
                image_url=poster,
                year=year,
                creator=None,
                genres=genres,
                description=item.get("overview"),
                external_url=f"https://www.themoviedb.org/{mt}/{item['id']}",
            )
        )
    return results


async def get_details(media_type: str, tmdb_id: str) -> MediaResult | None:
    if not settings.tmdb_api_key:
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/{media_type}/{tmdb_id}",
            headers=_headers(),
            params={"append_to_response": "credits"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        item = resp.json()

    title = item.get("title") or item.get("name", "")
    date = item.get("release_date") or item.get("first_air_date", "")
    year = int(date[:4]) if date and len(date) >= 4 else None
    poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
    genres = [g["name"] for g in item.get("genres", [])]

    creator = None
    credits = item.get("credits", {})
    if media_type == "movie":
        directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
        creator = ", ".join(directors[:2]) if directors else None
    else:
        created_by = item.get("created_by", [])
        creator = ", ".join(c["name"] for c in created_by[:2]) if created_by else None

    watch_providers = await get_watch_providers(media_type, tmdb_id)

    return MediaResult(
        external_id=str(item["id"]),
        source="tmdb",
        media_type=media_type,
        title=title,
        image_url=poster,
        year=year,
        creator=creator,
        genres=genres,
        description=item.get("overview"),
        external_url=f"https://www.themoviedb.org/{media_type}/{item['id']}",
        watch_providers=watch_providers,
    )


async def get_watch_providers(media_type: str, tmdb_id: str, region: str = "US") -> list[dict]:
    if not settings.tmdb_api_key:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/{media_type}/{tmdb_id}/watch/providers", headers=_headers()
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    region_data = data.get("results", {}).get(region, {})
    providers = []
    seen = set()

    for provider_type in ["flatrate", "rent", "buy"]:
        for p in region_data.get(provider_type, []):
            pid = p["provider_id"]
            if pid in seen:
                continue
            seen.add(pid)
            logo = f"{LOGO_BASE}{p['logo_path']}" if p.get("logo_path") else None
            providers.append(
                {
                    "name": p["provider_name"],
                    "logo_url": logo,
                    "type": provider_type,
                }
            )
    return providers


async def get_trending(media_type: str = "all", time_window: str = "week", limit: int = 10) -> list[MediaResult]:
    """Get trending movies/TV from TMDB."""
    if not settings.tmdb_api_key:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/trending/{media_type}/{time_window}", headers=_headers()
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    results = []
    for item in data.get("results", [])[:limit]:
        mt = item.get("media_type", "movie")
        if mt not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name", "")
        date = item.get("release_date") or item.get("first_air_date", "")
        year = int(date[:4]) if date and len(date) >= 4 else None
        poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
        backdrop = f"https://image.tmdb.org/t/p/w1280{item['backdrop_path']}" if item.get("backdrop_path") else None
        genre_ids = item.get("genre_ids", [])
        genres = [GENRE_MAP.get(gid, "") for gid in genre_ids]
        genres = [g for g in genres if g]

        results.append(
            MediaResult(
                external_id=str(item["id"]),
                source="tmdb",
                media_type=mt,
                title=title,
                image_url=poster,
                year=year,
                creator=None,
                genres=genres,
                description=item.get("overview"),
                external_url=f"https://www.themoviedb.org/{mt}/{item['id']}",
                backdrop_url=backdrop,
            )
        )
    return results


# TMDB genre ID to name mapping
GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime",
    99: "Documentary", 18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History",
    27: "Horror", 10402: "Music", 9648: "Mystery", 10749: "Romance",
    878: "Science Fiction", 10770: "TV Movie", 53: "Thriller", 10752: "War",
    37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
    10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
    10768: "War & Politics",
}
