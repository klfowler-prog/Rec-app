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

import math


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
