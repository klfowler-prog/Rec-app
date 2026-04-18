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
