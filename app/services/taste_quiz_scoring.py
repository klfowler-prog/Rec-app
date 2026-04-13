"""Shared scoring logic for taste quizzes (movies, TV, books, podcasts).

Each media type has its own data module declaring:
  - ITEMS: list of {order, title, year|years, weights} dicts
  - AXES: list of {key, label, description} dicts
  - AXIS_KEYS: list of the axis keys in AXES, in order
  - PROFILES: list of {id, name, vector, description} dicts
  - RESPONSE_OPTIONS: list of {value, emoji, label, description} dicts
  - RATING_MAP: dict mapping quiz response values to 1-10 ratings
  - MIN_ANSWERED: int, minimum non-null responses to surface a profile

Then calls score_responses() below with its own data. The scorer is
entirely generic — no mention of films or shows or any media-specific
concept. Adding a new media type is just a data file + two endpoints.
"""

import json
import math
from datetime import datetime


def persist_quiz_result(db, user_id: int, quiz_slug: str, result: dict) -> None:
    """Save a quiz result to UserPreferences.quiz_results as JSON.
    Keyed by quiz_slug so each medium's result is stored separately
    and can be read independently by the recommendation prompts.

    Only persists on has_enough_data=True so we don't save thin
    partial results that would pollute the AI signals."""
    if not result.get("has_enough_data"):
        return
    from app.models import UserPreferences

    # Build the minimal record we want to keep: profiles (names +
    # similarities), axis_scores, answered count, and for books the
    # dominant module. No timestamps from the scorer — we add one.
    summary = {
        "answered_count": result.get("answered_count", 0),
        "axis_scores": result.get("axis_scores", {}),
        "profiles": [
            {"id": p.get("id"), "name": p.get("name"), "similarity": p.get("similarity")}
            for p in (result.get("profiles") or [])
        ],
        "updated_at": datetime.utcnow().isoformat(),
    }
    # Books-specific extras
    if "dominant_module" in result:
        summary["dominant_module"] = result.get("dominant_module")
    if "fiction_answered" in result:
        summary["fiction_answered"] = result.get("fiction_answered")
    if "nonfiction_answered" in result:
        summary["nonfiction_answered"] = result.get("nonfiction_answered")

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not prefs:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)

    try:
        existing = json.loads(prefs.quiz_results) if prefs.quiz_results else {}
        if not isinstance(existing, dict):
            existing = {}
    except (json.JSONDecodeError, TypeError):
        existing = {}

    existing[quiz_slug] = summary
    prefs.quiz_results = json.dumps(existing)
    db.commit()


def compute_next_quiz(db, user_id: int, current_slug: str | None = None) -> dict | None:
    """Return a hint for the next incomplete quiz the user could take,
    or None if all three are done. Used by the /score endpoints so
    the quiz result screen can offer the next quiz as its primary
    CTA — turning the result screen into a funnel through the whole
    profile instead of a dead end.

    Iterates in the canonical order (movies → tv → books) and returns
    the first quiz whose results aren't persisted yet, excluding the
    quiz the user just finished (current_slug).
    """
    QUIZ_META = [
        {"slug": "movies", "label": "Movies", "href": "/quick-start/movies"},
        {"slug": "tv",     "label": "TV",     "href": "/quick-start/tv"},
        {"slug": "books",  "label": "Books",  "href": "/quick-start/books"},
    ]
    results = load_quiz_results(db, user_id)
    for meta in QUIZ_META:
        if meta["slug"] == current_slug:
            continue
        entry = results.get(meta["slug"]) if results else None
        if not entry or not entry.get("profiles"):
            return meta
    return None


def build_quiz_signals_block(db, user_id: int) -> str:
    """One-call convenience for recommendation prompts: loads the
    user's quiz results and formats them into a prompt block. Returns
    an empty string when there are no results, so the caller can
    include the output unconditionally."""
    return format_quiz_signals_for_prompt(load_quiz_results(db, user_id))


def load_quiz_results(db, user_id: int) -> dict:
    """Return the user's saved quiz results keyed by quiz slug, or
    an empty dict if none. Used by recommendation prompts to blend
    cross-medium taste signals."""
    from app.models import UserPreferences

    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if not prefs or not prefs.quiz_results:
        return {}
    try:
        data = json.loads(prefs.quiz_results)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def format_quiz_signals_for_prompt(quiz_results: dict) -> str:
    """Format the user's quiz results into a compact block the AI
    can read as taste signals. Returns an empty string if there are
    no quiz results — the caller should conditionally include the
    block only when it's non-empty.

    Output is intentionally concise because it goes into every
    recommendation prompt. Each medium gets one line with the
    dominant profile(s) and a short summary of which axes are high
    or low."""
    if not quiz_results:
        return ""

    labels = {"movies": "Movies", "tv": "TV", "books": "Books"}
    lines: list[str] = ["## TASTE QUIZ SIGNALS (blend these across media types when recommending):"]
    for slug, label in labels.items():
        data = quiz_results.get(slug)
        if not data or not isinstance(data, dict):
            continue
        profiles = data.get("profiles") or []
        if not profiles:
            continue
        primary = profiles[0].get("name", "")
        secondary = profiles[1].get("name") if len(profiles) > 1 else None
        profile_str = primary
        if secondary:
            profile_str += f" / {secondary}"

        # Highlight the 3 strongest and 3 weakest axes so the AI
        # can cross-reference them into other media.
        scores = data.get("axis_scores") or {}
        if scores:
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            top = [k for k, v in ranked if v > 0][:3]
            bottom = [k for k, v in ranked if v < 0][-3:]
            axis_hint = ""
            if top:
                axis_hint += f" HIGH on {', '.join(top)}"
            if bottom:
                axis_hint += f"; LOW on {', '.join(bottom)}"
        else:
            axis_hint = ""

        extra = ""
        if slug == "books" and data.get("dominant_module"):
            extra = f" (dominant: {data['dominant_module']})"
        lines.append(f"- **{label}** lean: {profile_str}{axis_hint}{extra}")

    if len(lines) == 1:  # only the header, no actual data
        return ""
    lines.append("")
    lines.append(
        "INSTRUCTION: Use these signals to make CROSS-MEDIUM connections. "
        "If the user is a 'Patient Formalist' in film and 'The Long Game Player' in TV, "
        "recommend books that reward commitment and formal craft too. "
        "The quizzes give direction — your job is to BLEND them into a single coherent taste picture "
        "and recommend things that hit multiple signals at once, not just one."
    )
    return "\n".join(lines) + "\n"


def score_responses(
    responses: list[dict],
    items: list[dict],
    axis_keys: list[str],
    profiles: list[dict],
    min_answered: int,
) -> dict:
    """Score a list of {order, value} responses against item weights.

    Null values are excluded from the math entirely — not treated as
    zeros. Items with a null response contribute nothing. Returns the
    raw axis scores plus the top 2 profile matches by cosine similarity
    so the UI can present a direction blend rather than a single label.

    If the user answered fewer than min_answered non-null questions,
    returns has_enough_data=False so the UI can prompt them to keep
    going rather than pinning them to a profile the math can't support.
    """
    item_by_order = {it["order"]: it for it in items}

    # Initialize every axis to 0, then accumulate deltas from non-null
    # responses. weight * value where value ∈ {-1, 0, 1, 2}.
    axis_scores: dict[str, float] = {k: 0.0 for k in axis_keys}
    real_count = 0
    for r in responses:
        value = r.get("value")
        if value is None:
            continue
        item = item_by_order.get(r.get("order"))
        if not item:
            continue
        real_count += 1
        for axis, weight in item.get("weights", {}).items():
            if axis in axis_scores:
                axis_scores[axis] += weight * value

    if real_count < min_answered:
        return {
            "answered_count": real_count,
            "axis_scores": axis_scores,
            "profiles": [],
            "has_enough_data": False,
        }

    # Cosine similarity against each profile's signature vector.
    user_vec = [axis_scores[k] for k in axis_keys]
    norm_u = math.sqrt(sum(v * v for v in user_vec))
    ranked: list[dict] = []
    for profile in profiles:
        profile_vec = [profile["vector"].get(k, 0.0) for k in axis_keys]
        norm_p = math.sqrt(sum(v * v for v in profile_vec))
        if norm_u == 0 or norm_p == 0:
            continue
        dot = sum(a * b for a, b in zip(user_vec, profile_vec))
        similarity = dot / (norm_u * norm_p)
        ranked.append({
            "id": profile["id"],
            "name": profile["name"],
            "description": profile["description"],
            "similarity": round(similarity, 3),
        })
    ranked.sort(key=lambda p: p["similarity"], reverse=True)

    return {
        "answered_count": real_count,
        "axis_scores": axis_scores,
        "profiles": ranked[:2],  # top 2 — direction blend
        "has_enough_data": True,
    }
