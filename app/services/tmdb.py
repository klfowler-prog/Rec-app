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
    for item in data.get("results", [])[:15]:
        mt = item.get("media_type", media_type or "movie")
        if mt not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name", "")
        date = item.get("release_date") or item.get("first_air_date", "")
        year = int(date[:4]) if date and len(date) >= 4 else None
        poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
        popularity = item.get("popularity") or 0
        genre_ids = item.get("genre_ids", [])
        genres = [GENRE_MAP.get(gid, "") for gid in genre_ids]
        genres = [g for g in genres if g]

        results.append(
            (
                bool(poster),
                popularity,
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
                ),
            )
        )

    # Float results with a poster to the top, then by TMDB popularity.
    # TMDB's multi-search sometimes puts obscure alternate entries ahead
    # of the canonical popular one for common titles.
    results.sort(key=lambda t: (0 if t[0] else 1, -t[1]))
    return [r[2] for r in results]


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


# Tiered streaming service allowlist (TMDB provider IDs)
# Tier 1: Major services — get named badge with logo on cards
TIER1_PROVIDERS = {
    8: "Netflix",
    15: "Hulu",
    1899: "Max",       # HBO Max / Max
    337: "Disney+",
    9: "Prime Video",
    350: "Apple TV+",
    386: "Peacock",
    531: "Paramount+",
}
# Tier 2: Everything else that's flatrate — "Other streaming" badge
# (no explicit list needed — anything flatrate not in TIER1 is Tier 2)

# Tier 3: Rental/purchase services — "Rent/Buy" badge
TIER3_PROVIDERS = {
    2: "Apple TV",       # rental/buy
    3: "Google Play",
    10: "Amazon Video",  # rental/buy (distinct from Prime included)
    7: "Vudu",
    192: "YouTube",
}


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

            # Determine tier
            if provider_type == "flatrate" and pid in TIER1_PROVIDERS:
                tier = "major"
            elif provider_type == "flatrate":
                tier = "other"
            else:
                tier = "rental"

            providers.append(
                {
                    "provider_id": pid,
                    "name": p["provider_name"],
                    "logo_url": logo,
                    "type": provider_type,
                    "tier": tier,
                }
            )
    # Sort: major first, then other streaming, then rental
    tier_order = {"major": 0, "other": 1, "rental": 2}
    providers.sort(key=lambda p: tier_order.get(p["tier"], 9))
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


async def _fetch_list(path: str, limit: int = 20) -> list[MediaResult]:
    """Shared helper for TMDB list endpoints (now_playing, upcoming,
    on_the_air, etc.)."""
    if not settings.tmdb_api_key:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{BASE_URL}{path}", headers=_headers(), params={"page": 1})
        if resp.status_code != 200:
            return []
        data = resp.json()

    # Infer media type from path
    mt = "tv" if "/tv/" in path else "movie"
    results = []
    for item in data.get("results", [])[:limit]:
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
    # Float items with posters to the front
    results.sort(key=lambda r: 0 if r.image_url else 1)
    return results


async def get_movies_now_playing(limit: int = 20) -> list[MediaResult]:
    """Movies currently in theaters (US)."""
    return await _fetch_list("/movie/now_playing", limit)


async def get_movies_upcoming(limit: int = 20) -> list[MediaResult]:
    """Movies releasing soon — useful for 'new to streaming' as a proxy."""
    return await _fetch_list("/movie/upcoming", limit)


async def get_movies_popular(limit: int = 20) -> list[MediaResult]:
    """Currently popular movies — a decent 'what's hot on streaming right now' proxy."""
    return await _fetch_list("/movie/popular", limit)


async def get_tv_on_the_air(limit: int = 20) -> list[MediaResult]:
    """TV shows currently airing new episodes."""
    return await _fetch_list("/tv/on_the_air", limit)


async def get_tv_popular(limit: int = 20) -> list[MediaResult]:
    """Currently popular TV — 'what's hot on streaming' for TV."""
    return await _fetch_list("/tv/popular", limit)


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
