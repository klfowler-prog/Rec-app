"""User relationship management — invite, accept, decline, list partners,
and social proof (friends who rated this)."""
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import MediaEntry, User, UserRelationship

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
def compatibility(
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

    return {
        "overall": round(overall, 1),
        "shared_count": len(shared_titles),
        "by_type": {mt: round(pct, 1) for mt, pct in type_pcts.items()},
        "battles": battles[:5],
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
