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
            params={"append_to_response": "credits,watch/providers"},
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

    # Extract watch providers from appended response (avoids a second API call)
    watch_providers = _parse_watch_providers(item.get("watch/providers", {}))

    # Runtime: movies have `runtime`, TV has `episode_run_time` (list)
    if media_type == "movie":
        runtime = item.get("runtime")
    else:
        ert = item.get("episode_run_time") or []
        runtime = round(sum(ert) / len(ert)) if ert else None

    # Primary network for TV shows
    networks = item.get("networks") or []
    network = networks[0]["name"] if networks else None

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
        audience_score=item.get("vote_average"),
        audience_count=item.get("vote_count"),
        popularity=item.get("popularity"),
        runtime=runtime,
        status=item.get("status"),
        seasons=item.get("number_of_seasons"),
        episodes=item.get("number_of_episodes"),
        network=network,
    )


# Tiered streaming service allowlist (TMDB provider IDs)
# Tier 1: Major services — get named badge with logo on cards
TIER1_PROVIDERS = {
    8: "Netflix",
    15: "Hulu",
    1899: "Max",
    337: "Disney+",
    9: "Prime Video",
    350: "Apple TV+",
    386: "Peacock",
    531: "Paramount+",
    38: "BBC iPlayer",
    103: "All 4",
    380: "BritBox",
    21: "Stan",
    283: "Crunchyroll",
    385: "Binge",
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


def _parse_watch_providers(wp_data: dict, region: str = "US") -> list[dict]:
    """Parse watch/providers from an appended TMDB detail response."""
    region_data = wp_data.get("results", {}).get(region, {})
    providers = []
    seen: set[int] = set()

    for provider_type in ["flatrate", "rent", "buy"]:
        for p in region_data.get(provider_type, []):
            pid = p["provider_id"]
            if pid in seen:
                continue
            seen.add(pid)
            logo = f"{LOGO_BASE}{p['logo_path']}" if p.get("logo_path") else None

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
    tier_order = {"major": 0, "other": 1, "rental": 2}
    providers.sort(key=lambda p: tier_order.get(p["tier"], 9))
    return providers


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
    on_the_air, etc.).  Fetches multiple pages when limit > 20 so we
    get a wide pool for the AI scorer to pick from."""
    if not settings.tmdb_api_key:
        return []

    from datetime import datetime

    pages_needed = min((limit + 19) // 20, 5)  # up to 5 pages (100 items)
    all_raw: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for page in range(1, pages_needed + 1):
            resp = await client.get(
                f"{BASE_URL}{path}", headers=_headers(),
                params={"page": page, "region": "US"},
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            all_raw.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                break

    # Infer media type from path
    mt = "tv" if "/tv/" in path else "movie"
    current_year = datetime.now().year
    seen_ids: set[str] = set()
    results = []
    for item in all_raw:
        eid = str(item["id"])
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        title = item.get("title") or item.get("name", "")
        date = item.get("release_date") or item.get("first_air_date", "")
        year = int(date[:4]) if date and len(date) >= 4 else None

        # Skip re-releases (Fight Club, Bridesmaids, etc.)
        if year and year < current_year - 1:
            continue

        # Skip niche/foreign releases unlikely to be at a typical US theater.
        # English-language films need popularity >= 10, foreign films need >= 40
        # (only the biggest foreign releases like anime blockbusters get wide US runs).
        pop = item.get("popularity", 0)
        lang = item.get("original_language", "en")
        if lang == "en" and pop < 10:
            continue
        if lang != "en" and pop < 40:
            continue

        poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
        genre_ids = item.get("genre_ids", [])
        genres = [GENRE_MAP.get(gid, "") for gid in genre_ids]
        genres = [g for g in genres if g]
        results.append(
            MediaResult(
                external_id=eid,
                source="tmdb",
                media_type=mt,
                title=title,
                image_url=poster,
                year=year,
                creator=None,
                genres=genres,
                description=item.get("overview"),
                external_url=f"https://www.themoviedb.org/{mt}/{item['id']}",
                audience_score=item.get("vote_average"),
                audience_count=item.get("vote_count"),
                popularity=item.get("popularity"),
            )
        )
        if len(results) >= limit:
            break
    # Sort by popularity so the most widely-released films come first
    results.sort(key=lambda r: r.popularity or 0, reverse=True)
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


async def get_recommendations(media_type: str, tmdb_id: str, limit: int = 10) -> list[MediaResult]:
    """Get TMDB's 'recommendations' for a specific movie or TV show.
    These are editorially curated similar items — high quality candidates."""
    if not settings.tmdb_api_key:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{BASE_URL}/{media_type}/{tmdb_id}/recommendations",
            headers=_headers(), params={"page": 1},
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    results = []
    for item in data.get("results", [])[:limit]:
        mt = item.get("media_type", media_type)
        if mt not in ("movie", "tv"):
            continue
        title = item.get("title") or item.get("name", "")
        date = item.get("release_date") or item.get("first_air_date", "")
        year = int(date[:4]) if date and len(date) >= 4 else None
        poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
        genre_ids = item.get("genre_ids", [])
        genres = [GENRE_MAP.get(gid, "") for gid in genre_ids]
        genres = [g for g in genres if g]
        results.append(MediaResult(
            external_id=str(item["id"]), source="tmdb", media_type=mt,
            title=title, image_url=poster, year=year, creator=None,
            genres=genres, description=item.get("overview"),
            external_url=f"https://www.themoviedb.org/{mt}/{item['id']}",
            audience_score=item.get("vote_average"),
            audience_count=item.get("vote_count"),
            popularity=item.get("popularity"),
        ))
    return results


async def discover(
    media_type: str = "tv",
    with_genres: str = "",
    with_watch_providers: str = "",
    vote_average_gte: float = 6.0,
    sort_by: str = "popularity.desc",
    limit: int = 20,
) -> list[MediaResult]:
    """Use TMDB's /discover endpoint to find items by genre, provider, rating, etc."""
    if not settings.tmdb_api_key:
        return []

    params: dict = {
        "sort_by": sort_by,
        "vote_average.gte": vote_average_gte,
        "vote_count.gte": 50,
        "watch_region": "US",
        "page": 1,
    }
    if with_genres:
        params["with_genres"] = with_genres
    if with_watch_providers:
        params["with_watch_providers"] = with_watch_providers
        params["watch_region"] = "US"

    pages_needed = min((limit + 19) // 20, 3)
    all_raw: list[dict] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for page in range(1, pages_needed + 1):
            params["page"] = page
            resp = await client.get(
                f"{BASE_URL}/discover/{media_type}",
                headers=_headers(), params=params,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            all_raw.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                break

    seen: set[str] = set()
    results = []
    for item in all_raw:
        eid = str(item["id"])
        if eid in seen:
            continue
        seen.add(eid)
        title = item.get("title") or item.get("name", "")
        date = item.get("release_date") or item.get("first_air_date", "")
        year = int(date[:4]) if date and len(date) >= 4 else None
        poster = f"{IMAGE_BASE}{item['poster_path']}" if item.get("poster_path") else None
        genre_ids = item.get("genre_ids", [])
        genres = [GENRE_MAP.get(gid, "") for gid in genre_ids]
        genres = [g for g in genres if g]
        results.append(MediaResult(
            external_id=eid, source="tmdb", media_type=media_type,
            title=title, image_url=poster, year=year, creator=None,
            genres=genres, description=item.get("overview"),
            external_url=f"https://www.themoviedb.org/{media_type}/{item['id']}",
            audience_score=item.get("vote_average"),
            audience_count=item.get("vote_count"),
            popularity=item.get("popularity"),
        ))
        if len(results) >= limit:
            break
    return results
