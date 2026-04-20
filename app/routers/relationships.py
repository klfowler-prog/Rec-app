"""User relationship management — invite, accept, decline, list partners,
and social proof (friends who rated this)."""
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import MediaEntry, User, UserRecommendation, UserRelationship

router = APIRouter()


class InviteRequest(BaseModel):
    receiver_email: str = ""
    relationship_type: str = "friend"  # partner, family, friend


class InviteResponse(BaseModel):
    id: int
    invite_code: str
    invite_url: str
    status: str


@router.post("/invite")
def create_invite(
    req: InviteRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Create a relationship invitation. Returns an invite code/link.
    If receiver_email is provided and they're already on the platform,
    creates a direct pending invitation. Otherwise creates an open
    invite link anyone can accept."""
    invite_code = secrets.token_urlsafe(12)

    # Check if receiver exists
    receiver = None
    if req.receiver_email:
        receiver = db.query(User).filter(User.email == req.receiver_email.lower().strip()).first()

    if receiver:
        # Check for existing relationship
        existing = db.query(UserRelationship).filter(
            ((UserRelationship.sender_id == user.id) & (UserRelationship.receiver_id == receiver.id))
            | ((UserRelationship.sender_id == receiver.id) & (UserRelationship.receiver_id == user.id))
        ).first()
        if existing:
            if existing.status == "accepted":
                raise HTTPException(400, "You're already connected")
            if existing.status == "pending":
                return {"id": existing.id, "invite_code": existing.invite_code or invite_code,
                        "invite_url": f"/invite/{existing.invite_code or invite_code}", "status": "already_pending"}

    rel = UserRelationship(
        sender_id=user.id,
        receiver_id=receiver.id if receiver else None,
        relationship_type=req.relationship_type,
        status="pending",
        invite_code=invite_code,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)

    return {"id": rel.id, "invite_code": invite_code,
            "invite_url": f"/invite/{invite_code}", "status": "pending"}


@router.post("/accept/{invite_code}")
def accept_invite(
    invite_code: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Accept a relationship invitation by code."""
    rel = db.query(UserRelationship).filter(
        UserRelationship.invite_code == invite_code,
        UserRelationship.status == "pending",
    ).first()
    if not rel:
        raise HTTPException(404, "Invitation not found or already used")

    # Can't accept your own invite
    if rel.sender_id == user.id:
        raise HTTPException(400, "Can't accept your own invitation")

    # If receiver was pre-set, verify it's the right person
    if rel.receiver_id and rel.receiver_id != user.id:
        raise HTTPException(403, "This invitation is for someone else")

    rel.receiver_id = user.id
    rel.status = "accepted"
    rel.accepted_at = datetime.utcnow()
    db.commit()

    sender = db.query(User).filter(User.id == rel.sender_id).first()
    return {"status": "accepted", "partner_name": sender.name if sender else "Unknown",
            "relationship_type": rel.relationship_type}


@router.post("/decline/{invite_code}")
def decline_invite(
    invite_code: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Decline a relationship invitation."""
    rel = db.query(UserRelationship).filter(
        UserRelationship.invite_code == invite_code,
        UserRelationship.status == "pending",
    ).first()
    if not rel:
        raise HTTPException(404, "Invitation not found")
    rel.status = "declined"
    db.commit()
    return {"status": "declined"}


@router.get("/partners")
def list_partners(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """List all accepted partners for the current user."""
    rels = db.query(UserRelationship).filter(
        ((UserRelationship.sender_id == user.id) | (UserRelationship.receiver_id == user.id)),
        UserRelationship.status == "accepted",
    ).all()

    partners = []
    for rel in rels:
        partner_id = rel.receiver_id if rel.sender_id == user.id else rel.sender_id
        partner = db.query(User).filter(User.id == partner_id).first()
        if partner:
            # Determine sharing level for what WE can see of THEM
            my_sharing = rel.sender_sharing if rel.sender_id == user.id else rel.receiver_sharing
            their_sharing = rel.receiver_sharing if rel.sender_id == user.id else rel.sender_sharing
            partners.append({
                "id": partner.id,
                "name": partner.name,
                "picture": partner.picture,
                "relationship_type": rel.relationship_type,
                "relationship_id": rel.id,
                "their_sharing": their_sharing,
                "my_sharing": my_sharing,
                "paired_since": rel.accepted_at.isoformat() if rel.accepted_at else None,
            })

    return partners


@router.get("/pending")
def list_pending(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """List pending invitations for the current user (both sent and received)."""
    sent = db.query(UserRelationship).filter(
        UserRelationship.sender_id == user.id,
        UserRelationship.status == "pending",
    ).all()

    received = db.query(UserRelationship).filter(
        UserRelationship.receiver_id == user.id,
        UserRelationship.status == "pending",
    ).all()

    result = []
    for rel in sent:
        receiver = db.query(User).filter(User.id == rel.receiver_id).first() if rel.receiver_id else None
        result.append({
            "id": rel.id,
            "direction": "sent",
            "invite_code": rel.invite_code,
            "partner_name": receiver.name if receiver else "Open invite",
            "relationship_type": rel.relationship_type,
            "created_at": rel.created_at.isoformat(),
        })
    for rel in received:
        sender = db.query(User).filter(User.id == rel.sender_id).first()
        result.append({
            "id": rel.id,
            "direction": "received",
            "invite_code": rel.invite_code,
            "partner_name": sender.name if sender else "Unknown",
            "relationship_type": rel.relationship_type,
            "created_at": rel.created_at.isoformat(),
        })

    return result


@router.delete("/{relationship_id}")
def remove_relationship(
    relationship_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Remove a relationship (unpair)."""
    rel = db.query(UserRelationship).filter(
        UserRelationship.id == relationship_id,
        ((UserRelationship.sender_id == user.id) | (UserRelationship.receiver_id == user.id)),
    ).first()
    if not rel:
        raise HTTPException(404, "Relationship not found")
    db.delete(rel)
    db.commit()
    return {"status": "removed"}


@router.put("/{relationship_id}/sharing")
def update_sharing(
    relationship_id: int,
    sharing_level: str = Query(...),  # full, ratings_only, together_only
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Update your sharing level for a specific relationship."""
    if sharing_level not in ("full", "ratings_only", "together_only"):
        raise HTTPException(400, "Invalid sharing level")

    rel = db.query(UserRelationship).filter(
        UserRelationship.id == relationship_id,
        ((UserRelationship.sender_id == user.id) | (UserRelationship.receiver_id == user.id)),
    ).first()
    if not rel:
        raise HTTPException(404, "Relationship not found")

    if rel.sender_id == user.id:
        rel.sender_sharing = sharing_level
    else:
        rel.receiver_sharing = sharing_level
    db.commit()
    return {"status": "updated", "sharing_level": sharing_level}


@router.get("/compatibility/{partner_id}")
async def compatibility(
    partner_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Calculate taste compatibility between two users from their
    shared rated items. Returns overall %, per-type %, and the
    biggest disagreements (taste battles)."""
    # Get both users' rated items
    my_entries = db.query(MediaEntry).filter(
        MediaEntry.user_id == user.id, MediaEntry.rating.isnot(None)
    ).all()
    their_entries = db.query(MediaEntry).filter(
        MediaEntry.user_id == partner_id, MediaEntry.rating.isnot(None)
    ).all()

    my_rated = {e.title.lower(): e for e in my_entries}
    their_rated = {e.title.lower(): e for e in their_entries}

    # Find shared items (both rated)
    shared_titles = set(my_rated.keys()) & set(their_rated.keys())
    if len(shared_titles) < 3:
        return {"overall": None, "shared_count": len(shared_titles),
                "message": "Need at least 3 shared rated items for a compatibility score"}

    # Calculate compatibility: 100% = identical ratings, 0% = max disagreement
    # Each shared item contributes: 1 - abs(my_rating - their_rating) / 4
    # (max possible difference is 4 on a 1-5 scale)
    scores = []
    by_type: dict[str, list[float]] = {}
    battles: list[dict] = []

    for title in shared_titles:
        my_e = my_rated[title]
        their_e = their_rated[title]
        diff = abs((my_e.rating or 3) - (their_e.rating or 3))
        agreement = 1 - (diff / 4)
        scores.append(agreement)

        mt = my_e.media_type
        by_type.setdefault(mt, []).append(agreement)

        # Track disagreements for taste battles
        if diff >= 2:
            battles.append({
                "title": my_e.title,
                "media_type": mt,
                "my_rating": my_e.rating,
                "their_rating": their_e.rating,
                "diff": diff,
            })

    overall = (sum(scores) / len(scores)) * 100
    type_pcts = {mt: (sum(s) / len(s)) * 100 for mt, s in by_type.items()}

    # Sort battles by biggest disagreement
    battles.sort(key=lambda b: b["diff"], reverse=True)

    # AI summary of the pair's taste relationship
    summary = ""
    from app.config import settings
    if settings.gemini_api_key and len(shared_titles) >= 5:
        import asyncio
        from app import cache

        partner = db.query(User).filter(User.id == partner_id).first()
        cache_key = f"together_dna:{min(user.id, partner_id)}:{max(user.id, partner_id)}"
        cached_summary = cache.get(cache_key)
        if cached_summary:
            summary = cached_summary
        else:
            my_name = user.name.split()[0]
            their_name = partner.name.split()[0] if partner else "them"

            # Build shared taste lines
            both_loved = [t for t in shared_titles if my_rated[t].rating >= 4 and their_rated[t].rating >= 4]
            both_loved_lines = [f"- {my_rated[t].title} ({my_rated[t].media_type}): {my_name} {my_rated[t].rating}/5, {their_name} {their_rated[t].rating}/5" for t in list(both_loved)[:8]]
            battle_lines = [f"- {b['title']}: {my_name} {b['my_rating']}/5, {their_name} {b['their_rating']}/5" for b in battles[:5]]

            from app.services.gemini import generate  # noqa: E402

            prompt = f"""Write 2-3 warm, conversational sentences about what {my_name} and {their_name} have in common as media consumers — and where they differ. This is their "Together DNA."

They are {round(overall)}% compatible based on {len(shared_titles)} shared items.

THINGS THEY BOTH LOVE:
{chr(10).join(both_loved_lines) if both_loved_lines else 'Not enough shared favorites yet'}

BIGGEST DISAGREEMENTS:
{chr(10).join(battle_lines) if battle_lines else 'No major disagreements'}

Write like a friend summarizing their relationship's taste, not like a professor. Be specific — reference actual titles. Keep it to 2-3 sentences.
Example: "You and Josh both light up for dark, twisty thrillers — Gone Girl and Severance are right in your shared sweet spot. Where you split: Josh loves slow-burn prestige drama, but you'd rather something with a faster pulse."
"""
            try:
                text = (await generate(prompt)).strip().strip('"').strip()
                if text and len(text) < 500:
                    summary = text
                    cache.set(cache_key, summary, ttl_seconds=604800)
            except Exception:
                pass

    return {
        "overall": round(overall, 1),
        "shared_count": len(shared_titles),
        "by_type": {mt: round(pct, 1) for mt, pct in type_pcts.items()},
        "battles": battles[:5],
        "summary": summary,
    }


@router.post("/quick-pair/{partner_id}")
def quick_pair(
    partner_id: int,
    relationship_type: str = Query("friend"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Directly pair with another user (for small user bases where
    everyone can see everyone). Creates an accepted relationship
    immediately — no invite/accept flow needed."""
    if partner_id == user.id:
        raise HTTPException(400, "Can't pair with yourself")

    partner = db.query(User).filter(User.id == partner_id).first()
    if not partner:
        raise HTTPException(404, "User not found")

    # Check for existing relationship
    existing = db.query(UserRelationship).filter(
        ((UserRelationship.sender_id == user.id) & (UserRelationship.receiver_id == partner_id))
        | ((UserRelationship.sender_id == partner_id) & (UserRelationship.receiver_id == user.id))
    ).first()
    if existing:
        if existing.status == "accepted":
            return {"status": "already_paired"}
        existing.status = "accepted"
        existing.accepted_at = datetime.utcnow()
        db.commit()
        return {"status": "accepted", "partner_name": partner.name}

    rel = UserRelationship(
        sender_id=user.id,
        receiver_id=partner_id,
        relationship_type=relationship_type,
        status="accepted",
        accepted_at=datetime.utcnow(),
    )
    db.add(rel)
    db.commit()
    return {"status": "accepted", "partner_name": partner.name}


class RecommendToRequest(BaseModel):
    to_user_id: int
    title: str
    media_type: str
    external_id: str = ""
    source: str = ""
    image_url: str = ""
    note: str = ""


@router.post("/recommend")
def recommend_to_partner(
    req: RecommendToRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Send a personal recommendation to a paired partner."""
    # Verify they're paired
    rel = db.query(UserRelationship).filter(
        ((UserRelationship.sender_id == user.id) & (UserRelationship.receiver_id == req.to_user_id))
        | ((UserRelationship.sender_id == req.to_user_id) & (UserRelationship.receiver_id == user.id)),
        UserRelationship.status == "accepted",
    ).first()
    if not rel:
        raise HTTPException(403, "You're not paired with this person")

    rec = UserRecommendation(
        from_user_id=user.id,
        to_user_id=req.to_user_id,
        title=req.title,
        media_type=req.media_type,
        external_id=req.external_id or None,
        source=req.source or None,
        image_url=req.image_url or None,
        note=req.note or None,
    )
    db.add(rec)
    db.commit()
    return {"status": "sent", "id": rec.id}


@router.get("/recommendations-for-me")
def get_recommendations_for_me(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Get personal recommendations sent to the current user."""
    recs = db.query(UserRecommendation).filter(
        UserRecommendation.to_user_id == user.id,
    ).order_by(UserRecommendation.created_at.desc()).limit(10).all()

    result = []
    for r in recs:
        sender = db.query(User).filter(User.id == r.from_user_id).first()
        result.append({
            "id": r.id,
            "from_name": sender.name.split()[0] if sender else "Someone",
            "from_picture": sender.picture if sender else None,
            "title": r.title,
            "media_type": r.media_type,
            "external_id": r.external_id,
            "source": r.source,
            "image_url": r.image_url,
            "note": r.note,
            "seen": r.seen,
            "created_at": r.created_at.isoformat(),
        })

    # Mark as seen
    db.query(UserRecommendation).filter(
        UserRecommendation.to_user_id == user.id,
        UserRecommendation.seen == False,
    ).update({"seen": True})
    db.commit()

    return result


@router.get("/social-proof/{external_id}")
def social_proof(
    external_id: str,
    source: str = Query(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Lazy-loaded social proof: how many friends rated this item and
    what they thought. Returns a compact summary like '3 friends rated
    this 4.2/5 avg' — not individual names (unless <=2 friends)."""
    # Get accepted partner IDs
    rels = db.query(UserRelationship).filter(
        ((UserRelationship.sender_id == user.id) | (UserRelationship.receiver_id == user.id)),
        UserRelationship.status == "accepted",
    ).all()
    partner_ids = []
    for rel in rels:
        pid = rel.receiver_id if rel.sender_id == user.id else rel.sender_id
        partner_ids.append(pid)

    if not partner_ids:
        return {"count": 0}

    # Find partner ratings for this item
    partner_entries = db.query(MediaEntry).filter(
        MediaEntry.external_id == external_id,
        MediaEntry.user_id.in_(partner_ids),
        MediaEntry.rating.isnot(None),
    ).all()

    if not partner_entries:
        return {"count": 0}

    count = len(partner_entries)
    avg = round(sum(e.rating for e in partner_entries) / count, 1)

    # For 1-2 friends, show names. For 3+, just show count.
    if count <= 2:
        names = []
        for e in partner_entries:
            p = db.query(User).filter(User.id == e.user_id).first()
            if p:
                names.append(p.name.split()[0])
        label = " and ".join(names) + f" rated this {avg}/5"
    else:
        label = f"{count} friends rated this {avg}/5 avg"

    return {"count": count, "avg": avg, "label": label}


@router.get("/partner-fit/{media_type}/{external_id}")
def partner_fit(
    media_type: str,
    external_id: str,
    title: str = Query(""),
    genres: str = Query(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Predict how well a specific media item would fit each of the
    user's partners, using a simple genre-based heuristic (no AI)."""
    # 1. Get all accepted partners (same query as list_partners)
    rels = db.query(UserRelationship).filter(
        ((UserRelationship.sender_id == user.id) | (UserRelationship.receiver_id == user.id)),
        UserRelationship.status == "accepted",
    ).all()

    partner_ids = []
    partner_meta: dict[int, dict] = {}
    for rel in rels:
        pid = rel.receiver_id if rel.sender_id == user.id else rel.sender_id
        partner = db.query(User).filter(User.id == pid).first()
        if partner:
            partner_ids.append(pid)
            partner_meta[pid] = {
                "id": partner.id,
                "name": partner.name,
                "picture": partner.picture,
                "relationship_type": rel.relationship_type,
            }

    if not partner_ids:
        return []

    # Parse incoming genres
    item_genres = {g.strip().lower() for g in genres.split(",") if g.strip()} if genres else set()

    results = []
    for pid in partner_ids:
        # Get partner's rated items in this media_type
        rated = db.query(MediaEntry).filter(
            MediaEntry.user_id == pid,
            MediaEntry.media_type == media_type,
            MediaEntry.rating.isnot(None),
        ).all()

        if len(rated) < 3:
            continue

        # Overall average
        overall_avg = sum(e.rating for e in rated) / len(rated)

        if not item_genres:
            # No genres provided — use overall avg with penalty
            predicted = overall_avg - 0.3
        else:
            # Find genre-matching items
            genre_ratings = []
            for entry in rated:
                if entry.genres:
                    entry_genres = {g.strip().lower() for g in entry.genres.split(",")}
                    if entry_genres & item_genres:
                        genre_ratings.append(entry.rating)

            genre_count = len(genre_ratings)
            if genre_count >= 3:
                # Enough genre-matching ratings — use genre avg directly
                predicted = sum(genre_ratings) / genre_count
            elif genre_count > 0:
                # Blend genre avg with overall avg
                genre_avg = sum(genre_ratings) / genre_count
                predicted = (genre_avg * genre_count + overall_avg * 2) / (genre_count + 2)
            else:
                # No genre matches — use overall avg with penalty
                predicted = overall_avg - 0.3

        predicted = round(predicted, 1)
        if predicted >= 3.0:
            results.append({
                **partner_meta[pid],
                "predicted_rating": predicted,
            })

    # Sort by predicted rating descending, return top 3
    results.sort(key=lambda r: r["predicted_rating"], reverse=True)
    return results[:3]


class WatchTogetherRequest(BaseModel):
    partner_id: int
    title: str
    media_type: str
    external_id: str = ""
    source: str = ""
    image_url: str = ""


@router.post("/watch-together")
def watch_together(
    payload: WatchTogetherRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Add a media item to both the user's and their partner's queue
    as a 'watch together' item, tagged for easy filtering."""
    # Verify accepted relationship exists
    rel = db.query(UserRelationship).filter(
        ((UserRelationship.sender_id == user.id) & (UserRelationship.receiver_id == payload.partner_id))
        | ((UserRelationship.sender_id == payload.partner_id) & (UserRelationship.receiver_id == user.id)),
        UserRelationship.status == "accepted",
    ).first()
    if not rel:
        raise HTTPException(403, "You're not paired with this person")

    created = []
    for uid, partner_tag_id in [(user.id, payload.partner_id), (payload.partner_id, user.id)]:
        # Check if entry already exists for this user
        existing = db.query(MediaEntry).filter(
            MediaEntry.user_id == uid,
            MediaEntry.external_id == payload.external_id,
            MediaEntry.source == payload.source,
        ).first()

        tag = f"watch-with:{partner_tag_id}"

        if existing:
            # Add the tag if not already present
            current_tags = existing.tags or ""
            if tag not in current_tags:
                existing.tags = f"{current_tags},{tag}" if current_tags else tag
            created.append("existing")
        else:
            entry = MediaEntry(
                user_id=uid,
                external_id=payload.external_id,
                source=payload.source or "unknown",
                title=payload.title,
                media_type=payload.media_type,
                image_url=payload.image_url or None,
                status="want_to_consume",
                tags=tag,
            )
            db.add(entry)
            created.append("created")

    db.commit()
    return {"status": "ok", "entries": created}
