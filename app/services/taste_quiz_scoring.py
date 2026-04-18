"""Shared scoring logic for taste quizzes (movies, TV, books, podcasts).

Each media type has its own data module declaring:
  - ITEMS: list of {order, title, year|years, weights} dicts
  - AXES: list of {key, label, description} dicts
  - AXIS_KEYS: list of the axis keys in AXES, in order
  - PROFILES: list of {id, name, vector, description} dicts
  - RESPONSE_OPTIONS: list of {value, emoji, label, description} dicts
  - RATING_MAP: dict mapping quiz response values to 1-5 ratings
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
    user's saved quiz results + onboarding answers and formats them
    into a prompt block for the AI to read as taste anchors. Returns
    an empty string when neither source has any data, so the caller
    can include the output unconditionally.

    The output combines two sections:
    1. USER ONBOARDING SIGNALS — the explicit 'I like these worlds'
       picks from Phase D1 (media mix + era + scenes). These are
       the strongest signal because the user typed them directly,
       not inferred from rating patterns.
    2. TASTE QUIZ SIGNALS — profile labels + axis scores from the
       movie/TV/books quizzes (the existing format).
    """
    results = load_quiz_results(db, user_id)
    onboarding_block = format_onboarding_signals_for_prompt(results.get("onboarding"))
    quiz_block = format_quiz_signals_for_prompt(results)
    return onboarding_block + quiz_block


# Human-readable labels for the scene/generation enums so the AI sees
# "anime + gaming culture" instead of "['anime', 'gaming_culture']".
_SCENE_LABELS = {
    "anime": "anime + manga",
    "action_thriller": "action and thrillers",
    "comedy": "comedies (sitcoms, buddy films, stand-up)",
    "horror": "horror and scary stuff",
    "scifi_fantasy": "sci-fi and fantasy",
    "prestige_drama": "prestige drama (literary / character-driven)",
    "romance": "romance",
    "true_crime": "true crime and true stories",
    "sports": "sports and competition",
    "music": "music and music history",
    "gaming_culture": "gaming culture (FNAF, Last of Us, Arcane, etc.)",
    "k_content": "K-dramas, K-pop, Korean content",
    "reality_tv": "reality TV",
    "indie_arthouse": "indie + arthouse",
    "docs_nonfiction": "documentaries and narrative nonfiction",
    "kids_family": "kids and family",
}

_GENERATION_LABELS = {
    "gen_z": "mostly recent stuff (last 5-10 years)",
    "millennial": "millennial canon (2000s-2010s)",
    "classic": "classic canon (70s-90s)",
    "mix": "a mix across eras",
}

_MEDIA_TYPE_LABELS = {
    "movie": "movies",
    "tv": "TV shows",
    "book_fiction": "fiction books",
    "book_nonfiction": "nonfiction books",
    "podcast": "podcasts",
}


def format_onboarding_signals_for_prompt(onboarding: dict | None) -> str:
    """Format saved onboarding answers into a compact prompt block.
    Returns an empty string when the user hasn't completed the wizard
    so the caller can include the output unconditionally."""
    if not onboarding or not isinstance(onboarding, dict):
        return ""

    media_types = onboarding.get("media_types") or []
    generation = onboarding.get("generation") or "mix"
    scenes = onboarding.get("scenes") or []

    # Nothing worth reporting if all three are empty / default.
    if not media_types and not scenes and generation == "mix":
        return ""

    lines = ["## USER ONBOARDING SIGNALS (the user explicitly told us these — weight them strongly):"]

    if media_types:
        pretty = ", ".join(_MEDIA_TYPE_LABELS.get(m, m) for m in media_types)
        lines.append(f"- **Media mix**: {pretty}")

    if generation and generation != "mix":
        lines.append(f"- **Era lean**: {_GENERATION_LABELS.get(generation, generation)}")

    if scenes:
        pretty_scenes = ", ".join(_SCENE_LABELS.get(s, s) for s in scenes)
        lines.append(f"- **Taste territories**: {pretty_scenes}")

    lines.append("")
    lines.append(
        "INSTRUCTION: These are the user's declared preferences — the 'worlds' "
        "they told us they're into. Weight recommendations that land in these "
        "territories strongly over ones that don't, even if the alternative "
        "sounds equally good on paper. A user who picked 'anime + gaming culture' "
        "wants anime and gaming-adjacent picks first; only reach outside those "
        "worlds when the user's message explicitly asks for something different."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


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


# Valid scene tags (Step 2b of the onboarding wizard). Items in the
# quiz pools are tagged with the same vocabulary in Phase D2 so the
# filter algorithm at quiz load time can match user picks against
# item scene tags. Keep this list in sync with the chip list in
# templates/onboarding.html.
ONBOARDING_SCENES = [
    "feelgood_comfort", "comedy", "romance", "action_thriller",
    "suspense_mystery", "horror", "scifi_fantasy", "prestige_drama",
    "true_crime", "history_war", "cooking_food", "self_improvement",
    "faith_family", "docs_nonfiction", "sports", "anime",
    "k_content", "gaming_culture", "music", "reality_tv",
    "indie_arthouse", "kids_family",
]
ONBOARDING_GENERATIONS = ["gen_z", "millennial", "classic", "mix"]
ONBOARDING_MEDIA_TYPES = ["movie", "tv", "book_fiction", "book_nonfiction", "podcast"]


def save_onboarding(db, user_id: int, answers: dict) -> dict:
    """Persist the user's onboarding wizard answers under the
    'onboarding' key in UserPreferences.quiz_results. Validates the
    incoming dict against the allowed vocabularies above and
    silently drops anything unknown — never crashes the wizard.

    Returns the cleaned dict that was persisted, so the caller can
    echo it back to the client."""
    from app.models import UserPreferences

    VALID_SERVICES = {8, 9, 15, 21, 38, 103, 283, 337, 350, 380, 385, 386, 531, 1899}
    VALID_REGIONS = {"us", "uk", "au", "ca", "eu", "asia", "latam", "other"}
    VALID_AGE_RANGES = {"under_18", "18_35", "35_50", "over_50"}

    cleaned: dict = {
        "media_types": [t for t in (answers.get("media_types") or []) if t in ONBOARDING_MEDIA_TYPES],
        "generation": answers.get("generation") if answers.get("generation") in ONBOARDING_GENERATIONS else "mix",
        "scenes": [s for s in (answers.get("scenes") or []) if s in ONBOARDING_SCENES],
        "streaming_services": [int(s) for s in (answers.get("streaming_services") or []) if int(s) in VALID_SERVICES] if answers.get("streaming_services") else [],
        "media_regions": [r for r in (answers.get("media_regions") or []) if r in VALID_REGIONS],
        "age_range": answers.get("age_range") if answers.get("age_range") in VALID_AGE_RANGES else "",
        "completed_at": datetime.utcnow().isoformat(),
    }

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

    existing["onboarding"] = cleaned
    prefs.quiz_results = json.dumps(existing)
    db.commit()
    return cleaned


def load_streaming_services(db, user_id: int) -> list[int]:
    """Return the user's selected streaming service provider IDs, or empty list."""
    onboarding = load_onboarding(db, user_id)
    if not onboarding:
        return []
    return onboarding.get("streaming_services") or []


def load_media_regions(db, user_id: int) -> list[str]:
    """Return the user's selected media regions, or empty list."""
    onboarding = load_onboarding(db, user_id)
    if not onboarding:
        return []
    return onboarding.get("media_regions") or []


def load_age_range(db, user_id: int) -> str:
    """Return the user's age range ('under_18', '18_40', 'over_40') or empty string."""
    onboarding = load_onboarding(db, user_id)
    if not onboarding:
        return ""
    return onboarding.get("age_range") or ""


def load_onboarding(db, user_id: int) -> dict | None:
    """Return the user's saved onboarding answers, or None if they
    haven't completed the wizard yet. Always returns a dict shape
    when present so callers can do data.get('scenes') without
    KeyError."""
    return load_quiz_results(db, user_id).get("onboarding")


def get_onboarding_display(onboarding: dict | None) -> dict | None:
    """Format saved onboarding answers for UI display. Returns None
    if there's nothing to show, or a dict with three lists of
    human-readable labels the /taste template can iterate over:

        {
            "media_types": [("movie", "movies"), ("tv", "TV shows"), ...],
            "generation": ("gen_z", "mostly recent stuff (last 5-10 years)"),
            "scenes": [("anime", "anime + manga"), ...],
        }

    Each entry is a (slug, label) tuple so the template can still
    key by the raw slug when it wants (e.g. for icons or accent
    classes) while rendering the friendly label by default.
    Generation is a single tuple (or None if 'mix'/missing) since
    it's a single-value pick.
    """
    if not onboarding or not isinstance(onboarding, dict):
        return None

    media_types = onboarding.get("media_types") or []
    generation = onboarding.get("generation") or "mix"
    scenes = onboarding.get("scenes") or []

    # Nothing worth showing
    if not media_types and not scenes and generation == "mix":
        return None

    return {
        "media_types": [(m, _MEDIA_TYPE_LABELS.get(m, m)) for m in media_types],
        "generation": (generation, _GENERATION_LABELS.get(generation, generation)) if generation != "mix" else None,
        "scenes": [(s, _SCENE_LABELS.get(s, s)) for s in scenes],
    }


def filter_quiz_items_by_onboarding(
    items: list[dict],
    onboarding: dict | None,
    min_items: int = 15,
    max_items: int = 25,
) -> list[dict]:
    """Filter a tagged quiz item pool against the user's saved
    onboarding picks (generation + scenes). Items are expected to
    carry both 'generation' (list) and 'scenes' (list) keys — Phase
    D2a-c tagged the existing pools.

    Algorithm (from Part 4 of the plan):
    1. Generation filter: keep items where the user's generation is
       in the item's generation[] OR the item is tagged 'universal'.
       If the user picked 'mix' or has no onboarding saved, every
       item passes this step.
    2. Scene filter: from the generation-pass set, keep items where
       the user's scenes[] list has any overlap with the item's
       scenes[] list. If the user picked no scenes, every item
       passes this step.
    3. Back-fill if the filtered set is < min_items:
       - First from the generation-pass set that didn't match any
         scene (they're at least in the right era).
       - Then from the full pool (last-resort catch-all).
       Never return fewer than min_items if the pool contains that
       many — undershooting the minimum is what breaks the current
       quiz experience for users outside the prestige-canon slice.
    4. Sort: scene-overlap-count desc (best matches first), then
       by original item.order asc for stable presentation.
    5. Cap at max_items.

    When the user has no onboarding saved, returns the first
    max_items of the pool unchanged — preserving today's behavior
    for users who skipped the wizard.
    """
    if not onboarding:
        return items[:max_items]

    user_gen = onboarding.get("generation") or "mix"
    user_scenes = set(onboarding.get("scenes") or [])

    def passes_gen(item: dict) -> bool:
        if user_gen == "mix":
            return True
        item_gens = set(item.get("generation") or [])
        # 'universal' items always pass the generation filter — they're
        # cross-generational hits that should anchor any user's quiz.
        return user_gen in item_gens or "universal" in item_gens

    def scene_overlap(item: dict) -> int:
        if not user_scenes:
            return 0
        return len(user_scenes & set(item.get("scenes") or []))

    gen_pass = [it for it in items if passes_gen(it)]

    if not user_scenes:
        # Scene step is a no-op when the user picked nothing.
        filtered = list(gen_pass)
    else:
        filtered = [it for it in gen_pass if scene_overlap(it) > 0]

    # Back-fill pass 1: add every item that passed the generation
    # filter but didn't match any scene. Not "up to the minimum" —
    # we want the user's whole era cohort since all of it is at
    # least era-appropriate. The final max_items cap enforces the
    # ceiling.
    if len(filtered) < max_items and user_scenes:
        seen_orders = {it.get("order") for it in filtered}
        for it in gen_pass:
            if it.get("order") not in seen_orders:
                filtered.append(it)
                seen_orders.add(it.get("order"))

    # Back-fill pass 2: if we're STILL below the minimum after adding
    # the full generation cohort, reach into the rest of the pool so
    # the user never sees fewer than min_items (e.g. a gen_z user
    # whose era has fewer than 15 items in the current pool).
    if len(filtered) < min_items:
        seen_orders = {it.get("order") for it in filtered}
        for it in items:
            if it.get("order") not in seen_orders:
                filtered.append(it)
                seen_orders.add(it.get("order"))
            if len(filtered) >= min_items:
                break

    filtered.sort(key=lambda it: (-scene_overlap(it), it.get("order", 9999)))
    return filtered[:max_items]


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
