from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MediaEntry
from app.schemas import MediaEntryCreate, MediaEntryResponse, MediaEntryUpdate, ProfileStats

router = APIRouter()


@router.get("/", response_model=list[MediaEntryResponse])
def list_profile(
    media_type: str | None = None,
    status: str | None = None,
    sort: str = "recent",
    db: Session = Depends(get_db),
):
    query = db.query(MediaEntry)
    if media_type:
        query = query.filter(MediaEntry.media_type == media_type)
    if status:
        query = query.filter(MediaEntry.status == status)
    if sort == "rating":
        query = query.order_by(MediaEntry.rating.desc().nullslast())
    elif sort == "title":
        query = query.order_by(MediaEntry.title.asc())
    else:
        query = query.order_by(MediaEntry.created_at.desc())
    return query.all()


@router.post("/", response_model=MediaEntryResponse)
def add_to_profile(entry: MediaEntryCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(MediaEntry)
        .filter(MediaEntry.external_id == entry.external_id, MediaEntry.source == entry.source)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already in your profile")
    db_entry = MediaEntry(**entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


@router.put("/{entry_id}", response_model=MediaEntryResponse)
def update_entry(entry_id: int, updates: MediaEntryUpdate, db: Session = Depends(get_db)):
    entry = db.query(MediaEntry).filter(MediaEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.query(MediaEntry).filter(MediaEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.get("/check/{source}/{external_id}")
def check_in_profile(source: str, external_id: str, db: Session = Depends(get_db)):
    entry = (
        db.query(MediaEntry)
        .filter(MediaEntry.external_id == external_id, MediaEntry.source == source)
        .first()
    )
    if entry:
        return {"in_profile": True, "entry": MediaEntryResponse.model_validate(entry)}
    return {"in_profile": False}


@router.get("/stats", response_model=ProfileStats)
def profile_stats(db: Session = Depends(get_db)):
    entries = db.query(MediaEntry).all()
    if not entries:
        return ProfileStats(total_entries=0, by_type={}, by_status={}, avg_rating=None, top_genres=[])

    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    genre_counts: dict[str, int] = {}
    ratings = []

    for e in entries:
        by_type[e.media_type] = by_type.get(e.media_type, 0) + 1
        by_status[e.status] = by_status.get(e.status, 0) + 1
        if e.rating is not None:
            ratings.append(e.rating)
        if e.genres:
            for g in e.genres.split(","):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1

    top_genres = sorted(genre_counts, key=genre_counts.get, reverse=True)[:5]
    avg_rating = sum(ratings) / len(ratings) if ratings else None

    return ProfileStats(
        total_entries=len(entries),
        by_type=by_type,
        by_status=by_status,
        avg_rating=round(avg_rating, 1) if avg_rating else None,
        top_genres=top_genres,
    )


@router.get("/fit-scores")
def get_fit_scores(db: Session = Depends(get_db)):
    """Calculate fit scores for 'want to consume' items based on genre overlap with highly-rated consumed items."""
    consumed = db.query(MediaEntry).filter(MediaEntry.status == "consumed").all()
    want = db.query(MediaEntry).filter(MediaEntry.status == "want_to_consume").all()

    if not consumed or not want:
        return []

    # Build genre preference weights from consumed items
    genre_weights: dict[str, float] = {}
    for e in consumed:
        if not e.genres:
            continue
        rating_boost = (e.rating / 10.0) if e.rating else 0.5
        for g in e.genres.split(","):
            g = g.strip()
            if g:
                genre_weights[g] = genre_weights.get(g, 0) + rating_boost

    # Normalize weights
    max_weight = max(genre_weights.values()) if genre_weights else 1
    genre_weights = {g: w / max_weight for g, w in genre_weights.items()}

    # Score each want-to-consume item
    scored = []
    for item in want:
        score = 0.0
        item_genres = []
        if item.genres:
            item_genres = [g.strip() for g in item.genres.split(",") if g.strip()]
        if item_genres:
            matches = sum(genre_weights.get(g, 0) for g in item_genres)
            score = min(10, round((matches / len(item_genres)) * 10, 1))
        else:
            score = 5.0  # Neutral score for items without genre data

        scored.append({
            "id": item.id,
            "external_id": item.external_id,
            "source": item.source,
            "title": item.title,
            "media_type": item.media_type,
            "image_url": item.image_url,
            "year": item.year,
            "creator": item.creator,
            "genres": item.genres,
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
