import asyncio
import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import MediaEntry, User
from app.schemas import MediaEntryCreate, MediaEntryResponse, MediaEntryUpdate, ProfileStats

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
    elif sort == "title":
        query = query.order_by(MediaEntry.title.asc())
    else:
        query = query.order_by(MediaEntry.created_at.desc())
    return query.all()


@router.post("/", response_model=MediaEntryResponse)
def add_to_profile(entry: MediaEntryCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    from app import cache

    existing = (
        db.query(MediaEntry)
        .filter(MediaEntry.user_id == user.id, MediaEntry.external_id == entry.external_id, MediaEntry.source == entry.source)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already in your profile")
    db_entry = MediaEntry(user_id=user.id, **entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    cache.mark_profile_changed()
    return db_entry


@router.put("/{entry_id}", response_model=MediaEntryResponse)
def update_entry(entry_id: int, updates: MediaEntryUpdate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entry = db.query(MediaEntry).filter(MediaEntry.id == entry_id, MediaEntry.user_id == user.id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
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


@router.get("/stats", response_model=ProfileStats)
def profile_stats(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user.id).all()
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
def get_fit_scores(user: User = Depends(require_user), db: Session = Depends(get_db)):
    consumed = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "consumed").all()
    want = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume").all()

    if not consumed or not want:
        return []

    genre_weights: dict[str, float] = {}
    for e in consumed:
        if not e.genres:
            continue
        rating_boost = (e.rating / 10.0) if e.rating else 0.5
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
    want = db.query(MediaEntry).filter(MediaEntry.user_id == user.id, MediaEntry.status == "want_to_consume").all()

    if not consumed or not want:
        return {"predicted": 0}

    rated = sorted(consumed, key=lambda e: e.rating or 0, reverse=True)
    taste_lines = [f"- {e.title} ({e.media_type}) — {e.rating}/10 [{e.genres or 'no genres'}]" for e in rated[:20]]

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
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel(model_name="gemini-3.1-flash-lite-preview")

            prompt = f"""You are a media taste predictor. Based on this user's rated items, predict how much they would enjoy each unrated item on a scale of 1-10.

User's rated items (their actual ratings):
{chr(10).join(taste_lines)}

Predict ratings for these items:
{chr(10).join(batch)}

Return ONLY valid JSON — a list of objects with "id" (the number after "id:") and "predicted_rating" (1-10, can use decimals like 7.5). No markdown, no explanation.

Be honest — not everything will be a high rating. Use the full 1-10 range."""

            response = model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                text = text.rsplit("```", 1)[0]
            predictions = json.loads(text)

            for pred in predictions:
                entry_id = pred.get("id")
                pr = pred.get("predicted_rating")
                if entry_id in want_map and pr is not None:
                    want_map[entry_id].predicted_rating = round(float(pr), 1)
                    total_predicted += 1

            db.commit()
        except Exception:
            db.rollback()

    return {"predicted": total_predicted}


@router.post("/import/goodreads")
async def import_goodreads(file: UploadFile = File(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    from app.services.open_library import search as search_books

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

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

        rating = gr_rating * 2 if gr_rating > 0 else None
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

    added_results = []
    for row_data, cover_data in enriched:
        entry = MediaEntry(
            user_id=user.id,
            external_id=cover_data["external_id"] or row_data["title"].lower().replace(" ", "-")[:50],
            source="open_library", title=row_data["title"], media_type="book",
            image_url=cover_data["image_url"], year=row_data["year"], creator=row_data["author"],
            genres=cover_data["genres"], description=cover_data["description"],
            status=row_data["status"], rating=row_data["rating"],
        )
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
