"""Tonight picker — chooses the single strongest unwatched recommendation.

No LLM calls. Reasons are templated from concrete signals in the user's
profile: anchor titles, creators, and partner ratings.
"""

import logging
from collections import Counter

from sqlalchemy.orm import Session

from app import cache
from app.models import MediaEntry, User, UserRelationship
from app.schemas import MediaResult, TonightPick

log = logging.getLogger(__name__)

# Minimum signal_score (0-10 scale) to surface a tonight pick.
# predicted_rating is 1-5 in the DB; signal_score = predicted_rating * 2.
MIN_SIGNAL_SCORE = 7.5  # equivalent to predicted_rating >= 3.75


def build_tonight(user: User, db: Session) -> TonightPick | None:
    """Pick the single strongest unwatched recommendation for tonight.

    Rules:
    - Must be unwatched AND unrated by the user
    - Prefer items with signal_score >= 7.5
    - Break ties by recency of matching anchor rating
    - Return None if no candidate clears the threshold
    """
    candidates = _get_candidates(user, db)
    if not candidates:
        return None

    # Find the best anchor for the winner (used in reason template)
    winner = candidates[0]
    signal_score = (winner.predicted_rating or 0) * 2

    reason = _build_reason(winner, user, db)
    if not reason:
        return None

    # Build the MediaResult item
    item = _entry_to_media_result(winner, signal_score)

    # Get provider names
    providers = _get_provider_names(winner)

    return TonightPick(item=item, reason=reason, providers=providers)


def _get_candidates(user: User, db: Session) -> list[MediaEntry]:
    """Get unrated queue items sorted by predicted_rating desc, then by
    recency of the closest anchor rating as tie-breaker."""
    queue_items = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "want_to_consume",
            MediaEntry.rating.is_(None),
            MediaEntry.predicted_rating.isnot(None),
        )
        .all()
    )

    # Filter to items above the threshold
    min_pr = MIN_SIGNAL_SCORE / 2  # convert back to 1-5 scale
    eligible = [e for e in queue_items if (e.predicted_rating or 0) >= min_pr]

    if not eligible:
        return []

    # Sort: highest predicted_rating first, then most recently added as tie-breaker
    eligible.sort(key=lambda e: (-(e.predicted_rating or 0), -(e.created_at.timestamp() if e.created_at else 0)))
    return eligible


def _entry_to_media_result(entry: MediaEntry, signal_score: float) -> MediaResult:
    genres = [g.strip() for g in entry.genres.split(",")] if entry.genres else []
    return MediaResult(
        external_id=entry.external_id,
        source=entry.source,
        media_type=entry.media_type,
        title=entry.title,
        image_url=entry.image_url,
        year=entry.year,
        creator=entry.creator,
        genres=genres,
        description=entry.description,
        signal_score=round(signal_score, 1),
    )


def _get_provider_names(entry: MediaEntry) -> list[str]:
    """Read cached provider names. Returns empty list if none cached."""
    if entry.media_type not in ("movie", "tv"):
        return []
    key = f"providers:{entry.media_type}:{entry.external_id}"
    cached = cache.get(key)
    if cached and isinstance(cached, list):
        return [p["name"] for p in cached if p.get("tier") == "major"]
    return []


def _build_reason(entry: MediaEntry, user: User, db: Session) -> str | None:
    """Pick the strongest signal template for this user+item pair.

    Priority:
    1. Creator match — user loved other work by the same creator
    2. Genre cluster — user's top-rated genre matches this item
    3. Partner signal — a connected partner rated this highly
    Falls back to None if we can't build a concrete reason.
    """
    # Try creator match first
    reason = _try_creator_reason(entry, user, db)
    if reason:
        return reason

    # Try genre cluster match
    reason = _try_genre_reason(entry, user, db)
    if reason:
        return reason

    # Try partner signal
    reason = _try_partner_reason(entry, user, db)
    if reason:
        return reason

    return None


def _try_creator_reason(entry: MediaEntry, user: User, db: Session) -> str | None:
    """If the user has rated other work by this creator highly, use that."""
    if not entry.creator:
        return None

    creator_lower = entry.creator.lower()
    loved_by_creator = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "consumed",
            MediaEntry.rating >= 4,
            MediaEntry.creator.isnot(None),
            MediaEntry.id != entry.id,
        )
        .all()
    )

    matches = [
        e for e in loved_by_creator
        if e.creator and creator_lower in e.creator.lower()
    ]

    if not matches:
        return None

    # Count how many they loved by this creator
    n = len(matches)
    best = max(matches, key=lambda e: e.rating or 0)
    if n == 1:
        return _truncate(f"You gave {best.title} a {_fmt_rating(best.rating)} — same creator.")
    return _truncate(f"{n} titles you've loved are from the same creator.")


def _try_genre_reason(entry: MediaEntry, user: User, db: Session) -> str | None:
    """Match against the user's top genre cluster, citing a specific anchor."""
    if not entry.genres:
        return None

    item_genres = {g.strip().lower() for g in entry.genres.split(",") if g.strip()}
    if not item_genres:
        return None

    # Get user's consumed+rated items to find genre anchors
    rated = (
        db.query(MediaEntry)
        .filter(
            MediaEntry.user_id == user.id,
            MediaEntry.status == "consumed",
            MediaEntry.rating >= 4,
            MediaEntry.genres.isnot(None),
        )
        .order_by(MediaEntry.rating.desc(), MediaEntry.rated_at.desc())
        .all()
    )

    if not rated:
        return None

    # Find the user's top genre that overlaps with this item
    genre_counts: Counter[str] = Counter()
    for e in rated:
        for g in e.genres.split(","):
            g = g.strip().lower()
            if g:
                genre_counts[g] += 1

    # Find best overlapping genre
    best_genre = None
    for genre, _count in genre_counts.most_common():
        if genre in item_genres:
            best_genre = genre
            break

    if not best_genre:
        return None

    # Find the best anchor in that genre
    anchor = None
    for e in rated:
        entry_genres = {g.strip().lower() for g in e.genres.split(",") if g.strip()}
        if best_genre in entry_genres:
            anchor = e
            break

    if not anchor:
        return None

    return _truncate(
        f"Matches your {best_genre} signal — you rated {anchor.title} a {_fmt_rating(anchor.rating)}."
    )


def _try_partner_reason(entry: MediaEntry, user: User, db: Session) -> str | None:
    """If a connected partner rated this item highly, cite them."""
    # Find accepted partner IDs
    partner_ids = _get_partner_ids(user, db)
    if not partner_ids:
        return None

    # Check if any partner has rated this item
    partner_entries = (
        db.query(MediaEntry, User)
        .join(User, User.id == MediaEntry.user_id)
        .filter(
            MediaEntry.user_id.in_(partner_ids),
            MediaEntry.external_id == entry.external_id,
            MediaEntry.source == entry.source,
            MediaEntry.rating.isnot(None),
            MediaEntry.rating >= 4,
        )
        .all()
    )

    if not partner_entries:
        return None

    best_entry, partner = max(partner_entries, key=lambda pair: pair[0].rating or 0)
    friend_name = (partner.name or "").split()[0]  # first name only

    return _truncate(
        f"{friend_name} rated this a {_fmt_rating(best_entry.rating)}, and your tastes overlap."
    )


def _get_partner_ids(user: User, db: Session) -> list[int]:
    """Get IDs of all accepted partners."""
    rels = (
        db.query(UserRelationship)
        .filter(
            UserRelationship.status == "accepted",
            (UserRelationship.sender_id == user.id) | (UserRelationship.receiver_id == user.id),
        )
        .all()
    )
    ids = []
    for r in rels:
        if r.sender_id == user.id:
            ids.append(r.receiver_id)
        else:
            ids.append(r.sender_id)
    return [i for i in ids if i is not None]


def _fmt_rating(rating: float | None) -> str:
    if rating is None:
        return "?"
    if rating == int(rating):
        return str(int(rating))
    return f"{rating:.1f}"


def _truncate(s: str, limit: int = 140) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "\u2026"
