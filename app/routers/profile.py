import asyncio
import csv
import io

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import DismissedItem, MediaEntry, RecEvent, User
from app.schemas import DismissedItemCreate, DismissedItemResponse, MediaEntryCreate, MediaEntryResponse, MediaEntryUpdate, ProfileStats

router = APIRouter()


@router.get("/", response_model=list[MediaEntryResponse])
def list_profile(
    media_type: str | None = None,
    status: str | None = None,
    sort: str = "recent",
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    query = db.query(MediaEntry).filter(MediaEntry.user_id == user.id)
    if media_type:
        query = query.filter(MediaEntry.media_type == media_type)
    if status:
        query = query.filter(MediaEntry.status == status)
    if sort == "rating":
        query = query.order_by(MediaEntry.rating.desc().nullslast())
    elif sort == "predicted":
        query = query.order_by(MediaEntry.predicted_rating.desc().nullslast(), MediaEntry.title.asc())
    elif sort == "title":
        query = query.order_by(MediaEntry.title.asc())
    else:
        query = query.order_by(MediaEntry.created_at.desc())
    return query.all()


async def _predict_single_item(user_id: int, entry_id: int):
    """Background task: predict rating for a single queue item."""
    import json
    import logging

    from app.config import settings

    if not settings.gemini_api_key:
        return

    log = logging.getLogger(__name__)
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        entry = db.query(MediaEntry).filter(MediaEntry.id == entry_id, MediaEntry.user_id == user_id).first()
        if not entry or entry.predicted_rating is not None:
            return

        consumed = db.query(MediaEntry).filter(
            MediaEntry.user_id == user_id, MediaEntry.status == "consumed", MediaEntry.rating.isnot(None)
        ).all()
        if not consumed:
            return

        rated = sorted(consumed, key=lambda e: e.rating or 0, reverse=True)
        top_lines = [f"- {e.title} ({e.media_type}) — {e.rating}/5 [{e.genres or 'no genres'}]" for e in rated[:15]]
        low = [e for e in consumed if (e.rating or 5) <= 2]
        low_lines = [f"- {e.title} ({e.media_type}) — {e.rating}/5 [{e.genres or 'no genres'}]" for e in low[:10]]

        from app.services.gemini import generate
        prompt = f"""Predict how much this user would enjoy a specific item on a 1-5 scale.

ITEMS THEY LOVED (rated 4-5):
{chr(10).join(top_lines)}

ITEMS THEY DISLIKED (rated 1-2):
{chr(10).join(low_lines) if low_lines else 'none recorded'}

PREDICT FOR:
- {entry.title} by {entry.creator or 'unknown'} ({entry.media_type}) [{entry.genres or 'no genres'}]

RULES:
- Be honest, not generous. Most items are a 3-3.5 for any given person. Only give 4+ for genuine taste matches.
- If the item's genre/tone/style resembles their disliked items, score it 1.5-2.5.
- If you don't recognize the item or can't tell, return 3.0 as a neutral score.
- A 5.0 means near-perfect match to their absolute favorites. Extremely rare.

Return ONLY a JSON object: {{"predicted_rating": 3.5}}"""

        text = (await generate(prompt, temperature=0)).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
        pr = parsed.get("predicted_rating")
        if pr is not None:
            pr_f = float(pr)
            if 1 <= pr_f <= 5:
                entry.predicted_rating = round(pr_f, 1)
                db.commit()
                log.info("Predicted rating for entry %d: %.1f", entry_id, pr_f)
    except Exception as e:
        log.debug("Single-item prediction failed for entry %d: %s", entry_id, e)
    finally:
        db.close()


@router.post("/", response_model=MediaEntryResponse)
def add_to_profile(
    entry: MediaEntryCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime as dt

    from app import cache

    existing = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.external_id == entry.external_id, MediaEntry.source == entry.source)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already in your profile")
    data = entry.model_dump()
    # If a rating is included, track when it was set
    if data.get("rating") is not None:
        db_entry = MediaEntry(user_id=user.id, rated_at=dt.utcnow(), **data)
    else:
        db_entry = MediaEntry(user_id=user.id, **data)
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    cache.mark_profile_changed()
    # Auto-predict rating for queue items in the background
    if db_entry.status == "want_to_consume" and db_entry.predicted_rating is None:
        background_tasks.add_task(_predict_single_item, user.id, db_entry.id)
    return db_entry


@router.put("/{entry_id}", response_model=MediaEntryResponse)
def update_entry(entry_id: int, updates: MediaEntryUpdate, background_tasks: BackgroundTasks, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from datetime import datetime as dt

    entry = db.query(MediaEntry).filter(MediaEntry.id == entry_id, MediaEntry.user_id == user.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    update_data = updates.model_dump(exclude_unset=True)
    # Track when a rating was actively set (for recent mood weighting)
    if "rating" in update_data and update_data["rating"] is not None:
        entry.rated_at = dt.utcnow()
    for field, value in update_data.items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    # Rating/status changes should bust recommendation caches so rated
    # items stop appearing in best bets / themes immediately.
    if "rating" in update_data or "status" in update_data:
        from app import cache
        cache.force_refresh()
    # Auto-predict when moved to queue without a prediction
    if entry.status == "want_to_consume" and entry.predicted_rating is None:
        background_tasks.add_task(_predict_single_item, user.id, entry.id)
    return entry


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from app import cache

    entry = db.query(MediaEntry).filter(MediaEntry.id == entry_id, MediaEntry.user_id == user.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    cache.mark_profile_changed()
    return {"ok": True}


@router.get("/check/{source}/{external_id}")
def check_in_profile(source: str, external_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entry = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.external_id == external_id, MediaEntry.source == source)
        .first()
    )
    if entry:
        return {"in_profile": True, "entry": MediaEntryResponse.model_validate(entry)}
    return {"in_profile": False}


@router.get("/top", response_model=list[MediaEntryResponse])
def profile_top(limit: int = 10, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Top rated items across all media types. Sorted by rating only —
    ties are broken by title alphabetically so the list is stable and
    doesn't shift based on when items were rated."""
    return (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None))
        .order_by(MediaEntry.rating.desc(), MediaEntry.title.asc())
        .limit(limit)
        .all()
    )


@router.get("/shape")
def profile_shape(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Taste shape data: rating histogram, media type distribution, genre breakdown."""
    # Only select the columns we actually need — much faster than loading full rows
    rows = db.query(
        MediaEntry.media_type,
        MediaEntry.rating,
        MediaEntry.genres,
    ).filter(MediaEntry.user_id == user.id).all()
    if not rows:
        return {"rating_histogram": {}, "type_distribution": {}, "top_genres": [], "total": 0}

    # Rating histogram (1-5 bins)
    rating_hist: dict[int, int] = {i: 0 for i in range(1, 6)}
    for media_type, rating, genres in rows:
        if rating is not None:
            bin_val = max(1, min(5, int(round(rating))))
            rating_hist[bin_val] += 1

    # Type distribution
    type_dist: dict[str, int] = {}
    for media_type, rating, genres in rows:
        type_dist[media_type] = type_dist.get(media_type, 0) + 1

    # Top genres with avg rating
    genre_data: dict[str, dict] = {}
    for media_type, rating, genres in rows:
        if genres:
            for g in genres.split(","):
                g = g.strip()
                if not g:
                    continue
                if g not in genre_data:
                    genre_data[g] = {"count": 0, "rating_sum": 0.0, "rating_count": 0}
                genre_data[g]["count"] += 1
                if rating is not None:
                    genre_data[g]["rating_sum"] += rating
                    genre_data[g]["rating_count"] += 1

    top_genres = []
    for genre, data in genre_data.items():
        avg = round(data["rating_sum"] / data["rating_count"], 1) if data["rating_count"] > 0 else None
        top_genres.append({"genre": genre, "count": data["count"], "avg_rating": avg})
    top_genres.sort(key=lambda g: g["count"], reverse=True)
    top_genres = top_genres[:10]

    return {
        "rating_histogram": rating_hist,
        "type_distribution": type_dist,
        "top_genres": top_genres,
        "total": len(rows),
    }


@router.get("/stats", response_model=ProfileStats)
def profile_stats(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.query(
        MediaEntry.media_type,
        MediaEntry.status,
        MediaEntry.rating,
        MediaEntry.genres,
    ).filter(MediaEntry.user_id == user.id).all()
    if not rows:
        return ProfileStats(total_entries=0, by_type={}, by_status={}, avg_rating=None, top_genres=[])

    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    genre_counts: dict[str, int] = {}
    ratings = []

    for media_type, status, rating, genres in rows:
        by_type[media_type] = by_type.get(media_type, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        if rating is not None:
            ratings.append(rating)
        if genres:
            for g in genres.split(","):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1

    top_genres = sorted(genre_counts, key=genre_counts.get, reverse=True)[:5]
    avg_rating = sum(ratings) / len(ratings) if ratings else None

    return ProfileStats(
        total_entries=len(rows),
        by_type=by_type,
        by_status=by_status,
        avg_rating=round(avg_rating, 1) if avg_rating else None,
        top_genres=top_genres,
    )


@router.get("/fit-scores")
def get_fit_scores(user: User = Depends(require_user), db: Session = Depends(get_db)):
    consumed = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "consumed").all()
    want = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume").all()

    if not consumed or not want:
        return []

    genre_weights: dict[str, float] = {}
    for e in consumed:
        if not e.genres:
            continue
        rating_boost = (e.rating / 5.0) if e.rating else 0.5
        for g in e.genres.split(","):
            g = g.strip()
            if g:
                genre_weights[g] = genre_weights.get(g, 0) + rating_boost

    max_weight = max(genre_weights.values()) if genre_weights else 1
    genre_weights = {g: w / max_weight for g, w in genre_weights.items()}

    scored = []
    for item in want:
        score = 0.0
        item_genres = [g.strip() for g in item.genres.split(",") if g.strip()] if item.genres else []
        if item_genres:
            matches = sum(genre_weights.get(g, 0) for g in item_genres)
            score = min(10, round((matches / len(item_genres)) * 10, 1))
        else:
            score = 5.0

        scored.append({
            "id": item.id, "external_id": item.external_id, "source": item.source,
            "title": item.title, "media_type": item.media_type, "image_url": item.image_url,
            "year": item.year, "creator": item.creator, "genres": item.genres, "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


@router.post("/predict-ratings")
async def predict_ratings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    import json

    from app.config import settings

    if not settings.gemini_api_key:
        return {"predicted": 0}

    consumed = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "consumed", MediaEntry.rating.isnot(None)).all()
    abandoned = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "abandoned").all()
    want = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume").all()

    if not consumed or not want:
        return {"predicted": 0}

    rated = sorted(consumed, key=lambda e: e.rating or 0, reverse=True)
    taste_lines = [f"- {e.title} ({e.media_type}) — {e.rating}/5 [{e.genres or 'no genres'}]" for e in rated[:20]]
    if abandoned:
        taste_lines.append("")
        taste_lines.append("Abandoned (treat as ~2/5 — user started but didn't finish):")
        for e in abandoned[:10]:
            taste_lines.append(f"- {e.title} ({e.media_type}) [{e.genres or 'no genres'}]")

    predict_lines = []
    want_map = {}
    for e in want:
        if e.predicted_rating is not None:
            continue
        predict_lines.append(f"- id:{e.id} | {e.title} by {e.creator or 'unknown'} ({e.media_type}) [{e.genres or 'no genres'}]")
        want_map[e.id] = e

    if not predict_lines:
        return {"predicted": 0, "message": "all items already have predictions"}

    total_predicted = 0
    for i in range(0, len(predict_lines), 30):
        batch = predict_lines[i:i + 30]
        try:
            from app.services.gemini import generate

            prompt = f"""Predict how much this user would enjoy each unrated item on a 1-5 scale.

User's taste profile (their actual ratings):
{chr(10).join(taste_lines)}

Predict ratings for these items:
{chr(10).join(batch)}

RULES:
- Be honest, not generous. Most items are a 3-3.5 for any given person.
- Only give 4+ for genuine taste matches — same genre, tone, and style as their top-rated items.
- If the item resembles their abandoned or low-rated items, score it 1.5-2.5.
- If you don't recognize the item, give 3.0 as a neutral score.
- 5.0 is extremely rare — near-perfect match to their absolute favorites only.
- Use the FULL 1-5 range. A realistic distribution: ~20% below 3, ~50% at 3-3.9, ~30% at 4+.

Return ONLY valid JSON — a list of objects with "id" (the number after "id:") and "predicted_rating" (1-5, one decimal). No markdown, no explanation."""

            text = (await generate(prompt, temperature=0)).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            predictions = json.loads(text)

            for pred in predictions:
                entry_id = pred.get("id")
                pr = pred.get("predicted_rating")
                if entry_id in want_map and pr is not None:
                    try:
                        pr_f = float(pr)
                        if 1 <= pr_f <= 5:
                            want_map[entry_id].predicted_rating = round(pr_f, 1)
                            total_predicted += 1
                    except (ValueError, TypeError):
                        pass

            db.commit()
        except Exception:
            db.rollback()

    return {"predicted": total_predicted}


@router.post("/dismiss", response_model=DismissedItemResponse)
def dismiss_item(item: DismissedItemCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from app import cache

    existing = (
        db.query(DismissedItem)
        .filter(DismissedItem.user_id == user.id, DismissedItem.title == item.title, DismissedItem.media_type == item.media_type)
        .first()
    )
    if existing:
        return existing

    db_item = DismissedItem(user_id=user.id, **item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    cache.mark_profile_changed()
    return db_item


@router.get("/dismissed", response_model=list[DismissedItemResponse])
def list_dismissed(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return db.query(DismissedItem).filter(DismissedItem.user_id == user.id).order_by(DismissedItem.created_at.desc()).all()


@router.post("/backfill-posters")
async def backfill_posters(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Re-search external APIs for profile entries that are missing an
    image_url or description, and update them in place."""
    from app.services.itunes import search as search_podcasts
    from app.services.unified_search import search_books
    from app.services.tmdb import search as search_tmdb

    missing = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            (MediaEntry.image_url.is_(None)) | (MediaEntry.description.is_(None)),
        )
        .all()
    )
    if not missing:
        return {"checked": 0, "updated": 0}

    async def find_and_patch(entry: MediaEntry) -> bool:
        try:
            if entry.media_type == "book":
                query = f"{entry.title} {entry.creator}" if entry.creator else entry.title
                matches = await search_books(query)
            elif entry.media_type in ("movie", "tv"):
                matches = await search_tmdb(entry.title, entry.media_type)
            elif entry.media_type == "podcast":
                matches = await search_podcasts(entry.title)
            else:
                return False
        except Exception:
            return False

        if not matches:
            return False

        title_lower = entry.title.lower().strip()
        best = matches[0]
        for m in matches:
            mt = m.title.lower().strip()
            if (mt == title_lower or mt.startswith(title_lower) or title_lower.startswith(mt)) and m.image_url:
                best = m
                break

        changed = False
        if not entry.image_url and best.image_url:
            entry.image_url = best.image_url
            changed = True
        if not entry.description and best.description:
            entry.description = best.description
            changed = True
        return changed

    updated = 0
    batch_size = 8
    for i in range(0, len(missing), batch_size):
        batch = missing[i : i + batch_size]
        results = await asyncio.gather(*[find_and_patch(e) for e in batch], return_exceptions=True)
        for r in results:
            if r is True:
                updated += 1
        db.commit()

    return {"checked": len(missing), "updated": updated}


@router.post("/import/goodreads")
async def import_goodreads(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    from app.services.unified_search import search_books

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames or "Title" not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="Invalid Goodreads CSV — missing 'Title' column")

    rows = []
    for row in reader:
        title = row.get("Title", "").strip()
        if not title:
            continue
        author = row.get("Author", "").strip()
        shelf = row.get("Exclusive Shelf", "").strip().lower()
        gr_rating = 0
        try:
            gr_rating = int(row.get("My Rating", "0"))
        except ValueError:
            pass
        year = None
        for col in ("Original Publication Year", "Year Published"):
            try:
                y = int(row.get(col, "").strip())
                if y > 0:
                    year = y
                    break
            except ValueError:
                pass

        if shelf == "currently-reading":
            status = "consuming"
        elif shelf == "to-read":
            status = "want_to_consume"
        else:
            status = "consumed"

        rating = gr_rating if gr_rating > 0 else None
        rows.append({
            "title": title, "author": author, "year": year,
            "status": status, "rating": rating,
            "isbn": row.get("ISBN13", "").strip().replace('="', "").replace('"', "") or row.get("ISBN", "").strip().replace('="', "").replace('"', ""),
        })

    existing_titles = {
        e.title.lower()
        for e in db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.media_type == "book").all()
    }

    new_rows = []
    skipped_results = []
    for row_data in rows:
        if row_data["title"].lower() in existing_titles:
            skipped_results.append({"title": row_data["title"], "status": "skipped", "reason": "already in profile"})
        else:
            new_rows.append(row_data)

    async def search_cover(row_data):
        title = row_data["title"]
        query = f"{title} {row_data['author']}" if row_data["author"] else title
        try:
            matches = await search_books(query)
            if matches:
                best = matches[0]
                return {"image_url": best.image_url, "external_id": best.external_id,
                        "genres": ", ".join(best.genres) if best.genres else None, "description": best.description}
        except Exception:
            pass
        return {"image_url": None, "external_id": row_data["isbn"] or title.lower().replace(" ", "-")[:50],
                "genres": None, "description": None}

    enriched = []
    for i in range(0, len(new_rows), 5):
        batch = new_rows[i : i + 5]
        batch_results = await asyncio.gather(*[search_cover(r) for r in batch])
        enriched.extend(zip(batch, batch_results))

    # Bulk save: add all entries first, flush, then commit once.
    # On integrity error, fall back to one-by-one to catch duplicates.
    added_results = []
    entries_to_add = []
    for row_data, cover_data in enriched:
        entry = MediaEntry(
            user_id=user.id,
            external_id=cover_data["external_id"] or row_data["title"].lower().replace(" ", "-")[:50],
            source="open_library", title=row_data["title"], media_type="book",
            image_url=cover_data["image_url"], year=row_data["year"], creator=row_data["author"],
            genres=cover_data["genres"], description=cover_data["description"],
            status=row_data["status"], rating=row_data["rating"],
        )
        entries_to_add.append((entry, row_data, cover_data))

    try:
        db.add_all([e[0] for e in entries_to_add])
        db.commit()
        for _, row_data, cover_data in entries_to_add:
            added_results.append({"title": row_data["title"], "status": "added",
                                  "rating": row_data["rating"], "image_url": cover_data["image_url"]})
    except Exception:
        db.rollback()
        # Fall back to individual inserts to isolate failures
        for entry, row_data, cover_data in entries_to_add:
            try:
                db.add(entry)
                db.commit()
                added_results.append({"title": row_data["title"], "status": "added",
                                      "rating": row_data["rating"], "image_url": cover_data["image_url"]})
            except Exception:
                db.rollback()
                added_results.append({"title": row_data["title"], "status": "skipped", "reason": "duplicate"})

    results = added_results + skipped_results
    added = sum(1 for r in results if r["status"] == "added")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    return {"total": len(rows), "added": added, "skipped": skipped, "results": results}


@router.post("/import/netflix")
async def import_netflix(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Import viewing history from Netflix CSV export."""
    from app.services.tmdb import search as tmdb_search

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames or "Title" not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="Invalid Netflix CSV — missing 'Title' column")

    rows = []
    for row in reader:
        title = row.get("Title", "").strip()
        if not title:
            continue
        # Netflix format: "Show Name: Season X: Episode Name" — extract the show/movie name
        clean_title = title.split(":")[0].strip()
        date = row.get("Date", "").strip()
        rows.append({"title": clean_title, "date": date})

    # Deduplicate — Netflix lists every episode, we just want unique show/movie names
    seen = set()
    unique_rows = []
    for row in rows:
        key = row["title"].lower()
        if key not in seen:
            seen.add(key)
            unique_rows.append(row)

    # Skip items already in profile
    existing_titles = {
        e.title.lower()
        for e in db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    }

    new_rows = []
    skipped_results = []
    for row_data in unique_rows:
        if row_data["title"].lower() in existing_titles:
            skipped_results.append({"title": row_data["title"], "status": "skipped", "reason": "already in profile"})
        else:
            new_rows.append(row_data)

    # Search TMDB for each title to get posters and metadata — in parallel batches
    async def search_tmdb(row_data):
        title = row_data["title"]
        try:
            # Search multi (movies + TV)
            matches = await tmdb_search(title, None)
            if matches:
                best = matches[0]
                return {
                    "image_url": best.image_url, "external_id": best.external_id,
                    "source": best.source, "media_type": best.media_type,
                    "genres": ", ".join(best.genres) if best.genres else None,
                    "description": best.description, "year": best.year,
                    "creator": best.creator,
                }
        except Exception:
            pass
        return {
            "image_url": None, "external_id": title.lower().replace(" ", "-")[:50],
            "source": "tmdb", "media_type": "movie",
            "genres": None, "description": None, "year": None, "creator": None,
        }

    enriched = []
    for i in range(0, len(new_rows), 5):
        batch = new_rows[i : i + 5]
        batch_results = await asyncio.gather(*[search_tmdb(r) for r in batch])
        enriched.extend(zip(batch, batch_results))

    added_results = []
    entries_to_add = []
    for row_data, tmdb_data in enriched:
        entry = MediaEntry(
            user_id=user.id,
            external_id=tmdb_data["external_id"],
            source=tmdb_data["source"],
            title=row_data["title"],
            media_type=tmdb_data["media_type"],
            image_url=tmdb_data["image_url"],
            year=tmdb_data["year"],
            creator=tmdb_data["creator"],
            genres=tmdb_data["genres"],
            description=tmdb_data["description"],
            status="consumed",
        )
        entries_to_add.append((entry, row_data, tmdb_data))

    try:
        db.add_all([e[0] for e in entries_to_add])
        db.commit()
        for _, row_data, tmdb_data in entries_to_add:
            added_results.append({"title": row_data["title"], "status": "added",
                                  "image_url": tmdb_data["image_url"], "media_type": tmdb_data["media_type"]})
    except Exception:
        db.rollback()
        for entry, row_data, tmdb_data in entries_to_add:
            try:
                db.add(entry)
                db.commit()
                added_results.append({"title": row_data["title"], "status": "added",
                                      "image_url": tmdb_data["image_url"], "media_type": tmdb_data["media_type"]})
            except Exception:
                db.rollback()
                added_results.append({"title": row_data["title"], "status": "skipped", "reason": "duplicate"})

    results = added_results + skipped_results
    added = sum(1 for r in results if r["status"] == "added")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    return {"total": len(unique_rows), "added": added, "skipped": skipped, "results": results}


class PlexImportRequest(PydanticBaseModel):
    server_url: str
    token: str


@router.post("/import/plex")
async def import_plex(req: PlexImportRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Import watch history from a Plex server via API.

    Calls the local or remote-accessible Plex server directly, walks
    every movie and show section with pagination, and persists any
    watched items to the profile. Notes:

    - For TV shows, Plex's `/library/sections/{id}/all` returns shows
      at the library level. The show-level `viewCount` is always 0;
      the real "have you watched this" signal is `viewedLeafCount`
      (episodes watched). Filter on that instead.
    - Plex will truncate long libraries without explicit pagination.
      Use X-Plex-Container-Start / X-Plex-Container-Size headers and
      loop until the server reports no more items.
    - Cloud Run can't reach private LAN addresses (192.168.x.x,
      10.x.x.x, etc). Users with home Plex servers must provide a
      Plex Remote Access URL (a plex.direct hostname) or set up a
      tunnel. We try to detect private IPs and surface a clear
      error instead of a cryptic connection timeout.
    """
    import ipaddress
    import logging
    from urllib.parse import urlparse

    import httpx

    from app.services.tmdb import search as tmdb_search

    log = logging.getLogger(__name__)

    # Validate URL — both to prevent SSRF and to give the user a
    # helpful error when they point us at a private LAN address.
    parsed = urlparse(req.server_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid Plex server URL")

    hostname = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise HTTPException(
                status_code=400,
                detail=(
                    "NextUp runs in the cloud and can't reach private network addresses "
                    f"like {hostname}. If your Plex server is on your home network, "
                    "enable Remote Access in Plex Settings → Remote Access, then use "
                    "the plex.direct URL it gives you (it'll look like "
                    "https://12-34-56-78.xxxx.plex.direct:32400)."
                ),
            )
    except ValueError:
        # hostname isn't an IP literal — a domain name like plex.direct
        pass

    server_url = req.server_url.rstrip("/")
    headers = {"X-Plex-Token": req.token, "Accept": "application/json"}
    log.info("import_plex [user=%d]: connecting to %s", user.id, server_url)

    # Reuse one client for all Plex requests. verify=False because
    # Plex's Remote Access endpoints use certs signed for *.plex.direct
    # which are valid, but local servers often use self-signed certs.
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        try:
            sections_resp = await client.get(f"{server_url}/library/sections", headers=headers)
            sections_resp.raise_for_status()
            sections = sections_resp.json()
        except httpx.ConnectError as e:
            log.error("import_plex: connect failed: %s", str(e))
            raise HTTPException(
                status_code=400,
                detail=(
                    "Couldn't reach your Plex server. Double-check the URL (including the "
                    ":32400 port) and that your Plex server is online and reachable from "
                    "the public internet. Home Plex servers usually need Remote Access "
                    "enabled so NextUp can reach them from the cloud."
                ),
            )
        except httpx.HTTPStatusError as e:
            log.error("import_plex: HTTP error: %s", str(e))
            detail = "Plex rejected the request — check your X-Plex-Token."
            if e.response.status_code == 401:
                detail = "Invalid X-Plex-Token. Grab a fresh one from View XML in the Plex web app."
            raise HTTPException(status_code=400, detail=detail)
        except Exception as e:
            log.exception("import_plex: unexpected error connecting to Plex")
            raise HTTPException(status_code=400, detail=f"Could not connect to Plex server: {str(e)}")

        # Walk every movie + show section with pagination.
        watched_items = []
        stats_per_section: list[str] = []
        for section in sections.get("MediaContainer", {}).get("Directory", []):
            section_type = section.get("type")
            section_key = section.get("key")
            section_title = section.get("title", "?")
            if section_type not in ("movie", "show"):
                continue

            page_size = 200
            start = 0
            section_count = 0
            while True:
                try:
                    page_headers = {
                        **headers,
                        "X-Plex-Container-Start": str(start),
                        "X-Plex-Container-Size": str(page_size),
                    }
                    items_resp = await client.get(
                        f"{server_url}/library/sections/{section_key}/all",
                        headers=page_headers,
                    )
                    items_resp.raise_for_status()
                    data = items_resp.json()
                except Exception as e:
                    log.warning(
                        "import_plex [user=%d]: section %s (%s) failed at offset %d: %s",
                        user.id, section_title, section_type, start, str(e),
                    )
                    break

                metadata = data.get("MediaContainer", {}).get("Metadata", [])
                if not metadata:
                    break

                for item in metadata:
                    title = item.get("title", "").strip()
                    if not title:
                        continue

                    # Filter for "watched" differently based on media
                    # type:
                    #   movie: viewCount > 0
                    #   show:  viewedLeafCount > 0 (at least one
                    #          episode watched)
                    if section_type == "movie":
                        if not item.get("viewCount", 0):
                            continue
                    else:  # show
                        if not item.get("viewedLeafCount", 0):
                            continue

                    media_type = "movie" if section_type == "movie" else "tv"
                    rating = None
                    if item.get("userRating"):
                        try:
                            rating = round(float(item["userRating"]), 1)
                        except (TypeError, ValueError):
                            rating = None

                    watched_items.append({
                        "title": title,
                        "year": item.get("year"),
                        "media_type": media_type,
                        "rating": rating,
                    })
                    section_count += 1

                # Did Plex return a full page? If yes, keep paginating.
                # If fewer items than page_size came back, this was
                # the last page.
                if len(metadata) < page_size:
                    break
                start += page_size

            stats_per_section.append(f"{section_title}={section_count}")

        log.info(
            "import_plex [user=%d]: fetched %d watched items (%s)",
            user.id, len(watched_items), ", ".join(stats_per_section) or "no sections",
        )

    # Deduplicate
    seen = set()
    unique_items = []
    for item in watched_items:
        key = item["title"].lower()
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    # Skip items already in profile
    existing_titles = {
        e.title.lower()
        for e in db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
    }

    new_items = []
    skipped_results = []
    for item in unique_items:
        if item["title"].lower() in existing_titles:
            skipped_results.append({"title": item["title"], "status": "skipped", "reason": "already in profile"})
        else:
            new_items.append(item)

    # Search TMDB for posters in parallel
    async def search_tmdb(item):
        try:
            matches = await tmdb_search(item["title"], item["media_type"])
            if matches:
                best = matches[0]
                return {
                    "image_url": best.image_url, "external_id": best.external_id,
                    "genres": ", ".join(best.genres) if best.genres else None,
                    "description": best.description,
                }
        except Exception:
            pass
        return {
            "image_url": None,
            "external_id": item["title"].lower().replace(" ", "-")[:50],
            "genres": None, "description": None,
        }

    enriched = []
    for i in range(0, len(new_items), 5):
        batch = new_items[i : i + 5]
        batch_results = await asyncio.gather(*[search_tmdb(it) for it in batch])
        enriched.extend(zip(batch, batch_results))

    added_results = []
    entries_to_add = []
    for item, tmdb_data in enriched:
        entry = MediaEntry(
            user_id=user.id,
            external_id=tmdb_data["external_id"],
            source="tmdb",
            title=item["title"],
            media_type=item["media_type"],
            image_url=tmdb_data["image_url"],
            year=item["year"],
            genres=tmdb_data["genres"],
            description=tmdb_data["description"],
            status="consumed",
            rating=item["rating"],
        )
        entries_to_add.append((entry, item, tmdb_data))

    try:
        db.add_all([e[0] for e in entries_to_add])
        db.commit()
        for _, item, tmdb_data in entries_to_add:
            added_results.append({"title": item["title"], "status": "added",
                                  "image_url": tmdb_data["image_url"], "rating": item["rating"]})
    except Exception:
        db.rollback()
        for entry, item, tmdb_data in entries_to_add:
            try:
                db.add(entry)
                db.commit()
                added_results.append({"title": item["title"], "status": "added",
                                      "image_url": tmdb_data["image_url"], "rating": item["rating"]})
            except Exception:
                db.rollback()
                added_results.append({"title": item["title"], "status": "skipped", "reason": "duplicate"})

    results = added_results + skipped_results
    added = sum(1 for r in results if r["status"] == "added")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    return {"total": len(unique_items), "added": added, "skipped": skipped, "results": results}


# ---------------------------------------------------------------------------
# Recommendation event tracking
# ---------------------------------------------------------------------------

class RecImpressionBatch(PydanticBaseModel):
    surface: str
    items: list[dict]


@router.post("/rec-events/impression")
def log_rec_impressions(
    batch: RecImpressionBatch,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Log that recommendations were shown to the user. Called once per
    surface load (e.g., best_bet, home_bundle_top_picks, theme_tonight_binge).
    Each item in the batch becomes a RecEvent row with outcome=null."""
    from datetime import datetime as dt

    events = []
    for item in batch.items[:20]:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        events.append(RecEvent(
            user_id=user.id,
            title=title,
            media_type=item.get("media_type", ""),
            surface=batch.surface,
            predicted_rating=item.get("predicted_rating"),
            shown_at=dt.utcnow(),
        ))
    if events:
        db.add_all(events)
        db.commit()
    return {"logged": len(events)}


@router.post("/rec-events/outcome")
def log_rec_outcome(
    data: dict,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Record what the user did with a recommendation. Finds the most
    recent impression matching (user, title) and stamps the outcome.
    Called by quickAdd, saveForLater, dismissItem, rateItem."""
    from datetime import datetime as dt

    title = (data.get("title") or "").strip()
    outcome = data.get("outcome", "")
    user_rating = data.get("user_rating")
    if not title or not outcome:
        return {"updated": False}

    event = (
        db.query(RecEvent)
        .filter(
            RecEvent.user_id == user.id,
            RecEvent.title == title,
            RecEvent.outcome.is_(None),
        )
        .order_by(RecEvent.shown_at.desc())
        .first()
    )
    if event:
        event.outcome = outcome
        event.user_rating = user_rating
        event.acted_at = dt.utcnow()
        db.commit()
        return {"updated": True}
    return {"updated": False}
