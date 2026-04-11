from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.schemas import MediaResult

router = APIRouter()


@router.get("/search", response_model=list[MediaResult])
async def search_media(q: str = Query(..., min_length=1), media_type: str | None = None):
    """Search across all media APIs."""
    from app.services.unified_search import unified_search

    return await unified_search(q, media_type)


class BulkSearchRequest(BaseModel):
    titles: list[str]


@router.post("/bulk-search")
async def bulk_search(req: BulkSearchRequest):
    """Search for multiple titles at once, returning the best match for each."""
    from app.services.unified_search import unified_search

    results = {}
    for title in req.titles:
        title = title.strip()
        if not title:
            continue
        matches = await unified_search(title, None)
        results[title] = matches[:3] if matches else []
    return results


@router.get("/{media_type}/{external_id}")
async def get_media_detail(media_type: str, external_id: str, source: str = ""):
    """Get detailed info for a specific media item."""
    from app.services.unified_search import get_detail

    return await get_detail(media_type, external_id, source)
