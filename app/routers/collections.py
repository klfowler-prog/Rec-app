import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import Collection, CollectionItem, MediaEntry, User

log = logging.getLogger(__name__)
router = APIRouter()


class CollectionResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    theme: str | None = None
    is_ai_generated: bool
    item_count: int = 0

    model_config = {"from_attributes": True}


class CollectionItemResponse(BaseModel):
    id: int
    external_id: str | None = None
    source: str | None = None
    title: str
    media_type: str
    image_url: str | None = None
    year: int | None = None
    creator: str | None = None
    reason: str | None = None
    order: int

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[CollectionResponse])
def list_collections(user: User = Depends(require_user), db: Session = Depends(get_db)):
    from sqlalchemy import func

    collections = (
        db.query(Collection)
        .filter(Collection.user_id == user.id)
        .order_by(Collection.created_at.desc())
        .all()
    )
    if not collections:
        return []

    # Batch fetch item counts in one query
    coll_ids = [c.id for c in collections]
    count_rows = (
        db.query(CollectionItem.collection_id, func.count(CollectionItem.id))
        .filter(CollectionItem.collection_id.in_(coll_ids))
        .group_by(CollectionItem.collection_id)
        .all()
    )
    count_map = {row[0]: row[1] for row in count_rows}

    return [
        CollectionResponse(
            id=c.id, title=c.title, description=c.description,
            theme=c.theme, is_ai_generated=c.is_ai_generated,
            item_count=count_map.get(c.id, 0),
        )
        for c in collections
    ]


@router.get("/{collection_id}")
def get_collection(collection_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == user.id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    items = (
        db.query(CollectionItem)
        .filter(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.order.asc(), CollectionItem.created_at.asc())
        .all()
    )
    return {
        "collection": CollectionResponse(
            id=collection.id, title=collection.title, description=collection.description,
            theme=collection.theme, is_ai_generated=collection.is_ai_generated,
            item_count=len(items),
        ),
        "items": [CollectionItemResponse.model_validate(i) for i in items],
    }


@router.delete("/{collection_id}")
def delete_collection(collection_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == user.id)
        .first()
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    # Cascade delete items
    db.query(CollectionItem).filter(CollectionItem.collection_id == collection_id).delete()
    db.delete(collection)
    db.commit()
    return {"ok": True}


@router.post("/generate")
async def generate_collections(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Use AI to generate 3-5 cross-medium collections from the user's taste profile."""
    from app.config import settings
    from app.services.gemini import generate
    from app.services.unified_search import unified_search

    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="AI not configured")

    entries = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)
    ).all()
    if len(entries) < 5:
        raise HTTPException(status_code=400, detail="Need at least 5 rated items to generate collections")

    # Build cross-medium taste summary
    by_type: dict[str, list] = {"movie": [], "tv": [], "book": [], "podcast": []}
    for e in entries:
        if e.rating and e.rating >= 3:
            by_type.setdefault(e.media_type, []).append(e)
    for mt in by_type:
        by_type[mt].sort(key=lambda x: x.rating or 0, reverse=True)

    label_map = {"movie": "MOVIES", "tv": "TV SHOWS", "book": "BOOKS", "podcast": "PODCASTS"}
    lines = []
    for mt, label in label_map.items():
        items = by_type.get(mt, [])[:10]
        if items:
            item_lines = [f"  - {e.title} ({e.year or '?'}) — {e.rating}/10 [{e.genres or ''}]" for e in items]
            lines.append(f"{label}:\n" + "\n".join(item_lines))
    profile_summary = "\n\n".join(lines)

    prompt = f"""You are a cross-medium taste curator. Based on this user's profile, create 3-4 THEMED COLLECTIONS that span multiple media types. Each collection is a "thread" of items (books, movies, TV, podcasts) that share the same essence — theme, tone, or narrative style.

{profile_summary}

TASK: Create 3-4 collections. Each should:
- Have a short, evocative title (e.g. "Slow Burn Thread", "Atmospheric Dread", "Morally Complex Protagonists")
- Have a one-sentence description citing specific items from their profile
- Include 6-8 items TOTAL spanning AT LEAST 3 different media types
- Mix items from their profile AND new recommendations they haven't tried

Return ONLY valid JSON, no markdown:
[
  {{
    "title": "Slow Burn Thread",
    "description": "one sentence citing specific items from their profile",
    "theme": "slow burn",
    "items": [
      {{"title": "...", "media_type": "movie|tv|book|podcast", "year": 2020, "reason": "why this fits the thread"}},
      ...
    ]
  }},
  ...
]"""

    try:
        text = (await generate(prompt)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
    except Exception as e:
        log.error("generate_collections parse failed: %s", str(e))
        raise HTTPException(status_code=500, detail="AI response parse failed")

    if not isinstance(parsed, list):
        raise HTTPException(status_code=500, detail="Unexpected AI response format")

    # Create collections in DB and search for posters
    async def enrich(item):
        try:
            matches = await unified_search(item.get("title", ""), item.get("media_type"))
            if matches:
                best = matches[0]
                return {
                    "external_id": best.external_id,
                    "source": best.source,
                    "title": best.title,
                    "media_type": best.media_type,
                    "image_url": best.image_url,
                    "year": best.year,
                    "creator": best.creator,
                    "reason": item.get("reason", ""),
                }
        except Exception:
            pass
        return {
            "external_id": None, "source": None,
            "title": item.get("title", ""),
            "media_type": item.get("media_type", "movie"),
            "image_url": None,
            "year": item.get("year"),
            "creator": None,
            "reason": item.get("reason", ""),
        }

    created_count = 0
    for coll_data in parsed[:4]:  # Limit to 4 collections max
        items = coll_data.get("items", [])
        if not items:
            continue

        enriched = await asyncio.gather(*[enrich(it) for it in items[:8]])

        collection = Collection(
            user_id=user.id,
            title=coll_data.get("title", "Untitled Collection"),
            description=coll_data.get("description", ""),
            theme=coll_data.get("theme"),
            is_ai_generated=True,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        for i, item in enumerate(enriched):
            ci = CollectionItem(
                collection_id=collection.id,
                external_id=item["external_id"],
                source=item["source"],
                title=item["title"],
                media_type=item["media_type"],
                image_url=item["image_url"],
                year=item["year"],
                creator=item["creator"],
                reason=item["reason"],
                order=i,
            )
            db.add(ci)
        db.commit()
        created_count += 1

    return {"created": created_count}
