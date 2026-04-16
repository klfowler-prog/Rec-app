"""Signal strength calculator — measures how much the AI knows about a user.

Five levels based on rated item count, with bonus consideration for
media type diversity and quiz completion. The signal strength feeds
into UI nudges that encourage users to rate more items.
"""

LEVELS = [
    {"level": 1, "min": 0,   "label": "Getting started",  "description": "Add a few favorites to get your first recommendations."},
    {"level": 2, "min": 10,  "label": "Building signal",  "description": "Patterns are emerging. Cross-medium connections are starting to work."},
    {"level": 3, "min": 25,  "label": "Strong signal",     "description": "Your taste profile is clear enough to share. Recommendations are getting personal."},
    {"level": 4, "min": 50,  "label": "Deep signal",       "description": "Recommendations are highly personalized. The AI knows your taste well."},
    {"level": 5, "min": 100, "label": "Full signal",       "description": "You're getting the best recommendations this app can produce."},
]

TARGET = 50  # The "magic number" for solid recommendations


def calculate_signal(db, user_id: int) -> dict:
    """Calculate a user's signal strength and return context for UI."""
    from app.models import MediaEntry

    # Count rated items
    rated = db.query(MediaEntry).filter(
        MediaEntry.user_id == user_id,
        MediaEntry.rating.isnot(None),
    ).count()

    # Count by media type for diversity nudges
    from sqlalchemy import func
    type_counts = dict(
        db.query(MediaEntry.media_type, func.count())
        .filter(MediaEntry.user_id == user_id, MediaEntry.rating.isnot(None))
        .group_by(MediaEntry.media_type)
        .all()
    )

    # Quiz completion
    from app.services.taste_quiz_scoring import load_quiz_results
    quiz_data = load_quiz_results(db, user_id)
    quizzes_done = sum(
        1 for t in ("movies", "tv", "books")
        if quiz_data and quiz_data.get(t, {}).get("profiles")
    )

    # Determine level
    current_level = LEVELS[0]
    for lvl in LEVELS:
        if rated >= lvl["min"]:
            current_level = lvl

    # Next level
    next_level = None
    for lvl in LEVELS:
        if lvl["level"] == current_level["level"] + 1:
            next_level = lvl
            break

    items_to_next = (next_level["min"] - rated) if next_level else 0

    # Build contextual nudge
    nudge = _build_nudge(rated, type_counts, quizzes_done, current_level["level"])

    return {
        "level": current_level["level"],
        "label": current_level["label"],
        "description": current_level["description"],
        "rated_count": rated,
        "target": TARGET,
        "items_to_next": max(0, items_to_next),
        "next_label": next_level["label"] if next_level else None,
        "bars": current_level["level"],  # out of 5
        "type_counts": type_counts,
        "quizzes_done": quizzes_done,
        "nudge": nudge,
    }


def _build_nudge(rated: int, type_counts: dict, quizzes_done: int, level: int) -> str:
    """Generate a specific, actionable nudge based on what's missing."""
    movies = type_counts.get("movie", 0)
    tv = type_counts.get("tv", 0)
    books = type_counts.get("book", 0)
    podcasts = type_counts.get("podcast", 0)

    # Priority 1: Very low signal
    if rated < 5:
        return "Add a few favorites to get your first recommendations."

    # Priority 2: Missing media types
    if books == 0 and (movies > 5 or tv > 5):
        return "You've rated movies and TV but no books — add a few to unlock cross-medium recommendations."
    if movies == 0 and tv == 0 and books > 5:
        return "Add some movies or TV shows to get recommendations that connect to what you read."
    if tv == 0 and movies > 5:
        return "No TV shows rated yet — add a few to round out your profile."

    # Priority 3: Quizzes
    if quizzes_done == 0 and rated >= 10:
        return "Want better, more personalized recommendations? Take a 5-minute taste quiz."
    if quizzes_done == 1 and rated >= 15:
        return f"You've done 1 of 3 quizzes — each one sharpens a different dimension of your taste."

    # Priority 4: General progress
    if rated < 25:
        return f"Add {25 - rated} more items to unlock stronger recommendations."
    if rated < 50:
        return f"{50 - rated} more items until your recommendations get deeply personal."
    if rated < 100:
        return f"Keep rating — {100 - rated} more to unlock the best recommendations possible."

    return "Your recommendations are as personal as they get."


# Celebration messages when crossing a level boundary
CELEBRATIONS = {
    2: {
        "emoji": "📡",
        "title": "Signal building!",
        "message": "Patterns are emerging — cross-medium connections are starting to work.",
    },
    3: {
        "emoji": "📶",
        "title": "Strong Signal achieved!",
        "message": "Your taste profile is clear enough to share. Recommendations are getting personal.",
    },
    4: {
        "emoji": "🎯",
        "title": "Deep Signal unlocked!",
        "message": "Recommendations are now highly personalized. The AI knows your taste.",
    },
    5: {
        "emoji": "⚡",
        "title": "Full Signal!",
        "message": "You're getting the best recommendations this app can produce.",
    },
}
