"""Book taste quiz — two-module (fiction + nonfiction) static data.

Fiction module: 20 titles, 8 axes
Nonfiction module: 10 titles, 9 axes (adds nonfiction_register)

Presented as Part 1 / Part 2 in the UI, scored independently, then
combined into a single profile match with module-dominance logic:
  - Both modules >= their minimum: combine axis scores, match against
    all 8 profiles, report which module drove the result.
  - Fiction >= 8, nonfiction < 5: fiction-only scoring.
  - Nonfiction >= 8, fiction < 8: nonfiction-only scoring.
  - Otherwise: not enough data.

Profile matching is cosine similarity against the 9-dimensional axis
vector. Fiction-only profiles ignore the nonfiction_register axis
(it's zeroed in the user vector when fiction-only).

Scoring logic partially delegates to taste_quiz_scoring.py but adds
module split + blend logic here.
"""

import math

# The 9 axes. Fiction uses the first 8; nonfiction uses all 9.
# nonfiction_register distinguishes narrative-first nonfiction
# (stories) from ideas-first nonfiction (arguments).
AXES: list[dict] = [
    {"key": "prose",            "label": "Prose Consciousness",     "description": "The writing itself is the point"},
    {"key": "plot",             "label": "Plot Dependence",         "description": "Needs narrative momentum to sustain"},
    {"key": "darkness",         "label": "Darkness Tolerance",      "description": "Engages bleak or punishing material"},
    {"key": "emotional",        "label": "Emotional Register",      "description": "Immersive, affecting, character-driven"},
    {"key": "irony",            "label": "Irony & Voice",           "description": "Strong, distinctive, or unreliable narrative voice"},
    {"key": "ideas",            "label": "Ideas Orientation",       "description": "Reads to think"},
    {"key": "moral_ambiguity",  "label": "Moral Ambiguity Comfort", "description": "Can inhabit genuinely complex or bad people"},
    {"key": "commitment",       "label": "Commitment Tolerance",    "description": "Willing to surrender to sprawling, slow-build works"},
    {"key": "nonfiction_register", "label": "Nonfiction Register",  "description": "Ideas-first argument (high) vs narrative story (low)"},
]

AXIS_KEYS: list[str] = [a["key"] for a in AXES]
FICTION_AXIS_KEYS: list[str] = [a["key"] for a in AXES if a["key"] != "nonfiction_register"]

RESPONSE_OPTIONS: list[dict] = [
    {"value": 2,    "emoji": "❤️",   "label": "Loved it",        "description": "A real favorite"},
    {"value": 1,    "emoji": "👍",   "label": "Liked it",        "description": "Enjoyed it"},
    {"value": 0,    "emoji": "😐",   "label": "It's fine",       "description": "Neutral"},
    {"value": -1,   "emoji": "👎",   "label": "Didn't click",    "description": "Not for me"},
    {"value": None, "emoji": "🚫",   "label": "Haven't read it", "description": "Skip"},
]

RATING_MAP: dict[int, int] = {2: 9, 1: 7, 0: 5, -1: 3}


# FICTION MODULE — 20 titles in accessible → challenging order.
# note_in_ui is shown as a small caveat under the title when present.
FICTION: list[dict] = [
    {"order": 1,  "title": "Harry Potter and the Sorcerer's Stone", "author": "J.K. Rowling",
     "years": "1997–2007", "note_in_ui": "Rate the series as a whole, not just this book",
     "weights": {"emotional": 1, "commitment": 1, "darkness": -2, "prose": -1}},
    {"order": 2,  "title": "The Kite Runner", "author": "Khaled Hosseini", "years": "2003",
     "weights": {"emotional": 2, "darkness": 1, "prose": -1, "ideas": -1}},
    {"order": 3,  "title": "To Kill a Mockingbird", "author": "Harper Lee", "years": "1960",
     "weights": {"emotional": 1, "irony": -1, "darkness": -1, "prose": 1}},
    {"order": 4,  "title": "Gone Girl", "author": "Gillian Flynn", "years": "2012",
     "weights": {"plot": 2, "darkness": 1, "irony": 1, "prose": -1}},
    {"order": 5,  "title": "Pride and Prejudice", "author": "Jane Austen", "years": "1813",
     "weights": {"prose": 1, "irony": 1, "emotional": 1, "plot": -1}},
    {"order": 6,  "title": "1984", "author": "George Orwell", "years": "1949",
     "weights": {"ideas": 2, "darkness": 1, "emotional": -1}},
    {"order": 7,  "title": "Normal People", "author": "Sally Rooney", "years": "2018",
     "weights": {"emotional": 2, "prose": 1, "plot": -1}},
    {"order": 8,  "title": "The Great Gatsby", "author": "F. Scott Fitzgerald", "years": "1925",
     "weights": {"prose": 2, "irony": 1, "ideas": 1, "plot": -1}},
    {"order": 9,  "title": "The Catcher in the Rye", "author": "J.D. Salinger", "years": "1951",
     "weights": {"irony": 2, "prose": 1, "emotional": 1, "plot": -1}},
    {"order": 10, "title": "Pachinko", "author": "Min Jin Lee", "years": "2017",
     "weights": {"commitment": 2, "emotional": 2, "plot": 1}},
    {"order": 11, "title": "Slaughterhouse-Five", "author": "Kurt Vonnegut", "years": "1969",
     "weights": {"irony": 2, "ideas": 1, "darkness": 1, "plot": -1}},
    {"order": 12, "title": "A Little Life", "author": "Hanya Yanagihara", "years": "2015",
     "weights": {"darkness": 2, "emotional": 2, "commitment": 2, "prose": 1}},
    {"order": 13, "title": "Catch-22", "author": "Joseph Heller", "years": "1961",
     "weights": {"irony": 2, "ideas": 1, "darkness": 1, "commitment": 1, "plot": -1}},
    {"order": 14, "title": "Crime and Punishment", "author": "Fyodor Dostoevsky", "years": "1866",
     "weights": {"moral_ambiguity": 2, "ideas": 1, "darkness": 1, "commitment": 1, "prose": 1}},
    {"order": 15, "title": "The Road", "author": "Cormac McCarthy", "years": "2006",
     "weights": {"darkness": 2, "prose": 2, "emotional": 1, "commitment": -1}},
    {"order": 16, "title": "One Flew Over the Cuckoo's Nest", "author": "Ken Kesey", "years": "1962",
     "weights": {"moral_ambiguity": 2, "irony": 1, "darkness": 1, "prose": 1}},
    {"order": 17, "title": "The Remains of the Day", "author": "Kazuo Ishiguro", "years": "1989",
     "weights": {"prose": 2, "irony": 1, "emotional": 1, "plot": -1}},
    {"order": 18, "title": "Beloved", "author": "Toni Morrison", "years": "1987",
     "weights": {"prose": 2, "darkness": 2, "emotional": 2, "irony": 1}},
    {"order": 19, "title": "Infinite Jest", "author": "David Foster Wallace", "years": "1996",
     "weights": {"commitment": 2, "prose": 2, "ideas": 1, "irony": 1, "plot": -2}},
    {"order": 20, "title": "Blood Meridian", "author": "Cormac McCarthy", "years": "1985",
     "weights": {"prose": 2, "darkness": 2, "irony": 1, "plot": -2}},
    # Additional mainstream/canonical fiction — sci-fi epic, YA,
    # modern bestsellers, contemporary literary. Gives readers more
    # surface to find titles they've actually read.
    {"order": 21, "title": "Dune", "author": "Frank Herbert", "years": "1965",
     "weights": {"commitment": 2, "ideas": 1, "prose": 1, "plot": 1}},
    {"order": 22, "title": "The Hunger Games", "author": "Suzanne Collins", "years": "2008",
     "weights": {"plot": 2, "emotional": 1, "darkness": 1, "prose": -1}},
    {"order": 23, "title": "The Seven Husbands of Evelyn Hugo", "author": "Taylor Jenkins Reid", "years": "2017",
     "weights": {"plot": 1, "emotional": 2, "prose": -1}},
    {"order": 24, "title": "Where the Crawdads Sing", "author": "Delia Owens", "years": "2018",
     "weights": {"emotional": 2, "plot": 1, "prose": 1, "darkness": 1}},
    {"order": 25, "title": "Tomorrow, and Tomorrow, and Tomorrow", "author": "Gabrielle Zevin", "years": "2022",
     "weights": {"emotional": 1, "ideas": 1, "prose": 1, "commitment": 1}},
]


# NONFICTION MODULE — 10 titles in presentation order.
# These carry the extra nonfiction_register axis: positive = ideas-
# first argument-driven (Sapiens, How to Change Your Mind), negative
# = narrative-first story-driven (Educated, The Years).
NONFICTION: list[dict] = [
    {"order": 1,  "title": "Educated", "author": "Tara Westover", "years": "2018",
     "weights": {"emotional": 2, "darkness": 1, "plot": 1, "prose": -1}},
    {"order": 2,  "title": "The Immortal Life of Henrietta Lacks", "author": "Rebecca Skloot", "years": "2010",
     "weights": {"emotional": 2, "moral_ambiguity": 1, "nonfiction_register": 1, "plot": 1}},
    {"order": 3,  "title": "When Breath Becomes Air", "author": "Paul Kalanithi", "years": "2016",
     "weights": {"emotional": 2, "darkness": 2, "prose": 1}},
    {"order": 4,  "title": "Sapiens", "author": "Yuval Noah Harari", "years": "2011",
     "weights": {"ideas": 2, "nonfiction_register": 2, "emotional": -1}},
    {"order": 5,  "title": "Into the Wild", "author": "Jon Krakauer", "years": "1996",
     "weights": {"moral_ambiguity": 2, "plot": 1, "emotional": 1}},
    {"order": 6,  "title": "The Body Keeps the Score", "author": "Bessel van der Kolk", "years": "2014",
     "weights": {"emotional": 1, "ideas": 1, "nonfiction_register": 1}},
    {"order": 7,  "title": "Say Nothing", "author": "Patrick Radden Keefe", "years": "2018",
     "weights": {"darkness": 2, "moral_ambiguity": 2, "plot": 1, "nonfiction_register": 1}},
    {"order": 8,  "title": "In Cold Blood", "author": "Truman Capote", "years": "1966",
     "weights": {"prose": 2, "darkness": 2, "moral_ambiguity": 1, "nonfiction_register": 1}},
    {"order": 9,  "title": "The Years", "author": "Annie Ernaux", "years": "2008",
     "weights": {"prose": 2, "irony": 1, "nonfiction_register": -1}},
    {"order": 10, "title": "How to Change Your Mind", "author": "Michael Pollan", "years": "2018",
     "weights": {"ideas": 2, "nonfiction_register": 1, "prose": 1}},
    # Additional nonfiction — two more ideas books, two more narrative
    # memoirs, one investigative. Broadens the surface to match the
    # fiction module's new size.
    {"order": 11, "title": "Atomic Habits", "author": "James Clear", "years": "2018",
     "weights": {"ideas": 2, "nonfiction_register": 2, "emotional": -1}},
    {"order": 12, "title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "years": "2011",
     "weights": {"ideas": 2, "nonfiction_register": 2, "commitment": 1, "emotional": -1}},
    {"order": 13, "title": "Just Mercy", "author": "Bryan Stevenson", "years": "2014",
     "weights": {"emotional": 2, "darkness": 1, "moral_ambiguity": 1, "nonfiction_register": -1}},
    {"order": 14, "title": "The Glass Castle", "author": "Jeannette Walls", "years": "2005",
     "weights": {"emotional": 2, "darkness": 1, "plot": 1, "prose": 1}},
    {"order": 15, "title": "Bad Blood", "author": "John Carreyrou", "years": "2018",
     "weights": {"plot": 2, "moral_ambiguity": 1, "darkness": 1, "nonfiction_register": -1}},
]


PROFILES: list[dict] = [
    {
        "id": "story_first",
        "name": "The Story First Reader",
        "vector": {"plot": 1.0, "prose": -1.0, "moral_ambiguity": -0.5},
        "description": "You read to find out what happens. Pacing matters more than sentences. You're not here to be impressed — you're here to be pulled through, and a book that loses its grip loses you.",
    },
    {
        "id": "prose_devotee",
        "name": "The Prose Devotee",
        "vector": {"prose": 1.0, "irony": 1.0, "plot": -1.0},
        "description": "The writing is the point. You'll follow a great sentence anywhere. Plot is scaffolding; what remains is language, rhythm, and the way a good page changes how you think.",
    },
    {
        "id": "emotional_immersive",
        "name": "The Emotional Immersive",
        "vector": {"emotional": 1.0, "darkness": 1.0, "commitment": 1.0},
        "description": "You want to feel everything. Length isn't a deterrent — it's an invitation. The best books leave a mark you carry for weeks, the kind of thing you can't shake even after you've finished.",
    },
    {
        "id": "ideas_reader",
        "name": "The Ideas Reader",
        "vector": {"ideas": 1.0, "moral_ambiguity": 1.0, "emotional": -1.0},
        "description": "Books are for changing how you think, not how you feel. A great argument matters more than a great sentence. You want work that leaves your head rearranged.",
    },
    {
        "id": "dark_ironist",
        "name": "The Dark Ironist",
        "vector": {"irony": 1.0, "darkness": 1.0, "emotional": -1.0},
        "description": "Earnestness is suspicious. You're drawn to books that know they're absurd — humor as delivery mechanism for something bleak, and the deadpan that makes the horror land harder.",
    },
    {
        "id": "warm_traditionalist",
        "name": "The Warm Traditionalist",
        "vector": {"emotional": 1.0, "darkness": -1.0, "prose": 0.3},
        "description": "You value story, character, and emotional truth in recognizable forms. The literary tradition isn't a constraint — it's the point. You want books that understand what story is for.",
    },
    {
        "id": "narrative_nonfiction",
        "name": "The Narrative Nonfiction Reader",
        "vector": {"emotional": 1.0, "plot": 1.0, "nonfiction_register": -1.0},
        "description": "True stories told with the pace and texture of novels. You want to feel like you're inside something real — to learn the world by living in it alongside someone who actually did.",
    },
    {
        "id": "ideas_first_nonfiction",
        "name": "The Ideas-First Nonfiction Reader",
        "vector": {"ideas": 1.0, "emotional": -0.5, "nonfiction_register": 1.0},
        "description": "Books are for changing how you think at scale. A great argument matters more than a great story. You read to rewire your mental model of something big.",
    },
]


FICTION_MIN = 7
NONFICTION_MIN = 6
NONFICTION_MIN_TO_USE = 4  # below this, fiction-only even if fiction met its minimum


def score_book_responses(responses: list[dict]) -> dict:
    """Score a two-module book quiz submission.

    Each response carries a `module` field ("fiction" or "nonfiction")
    in addition to the usual order + value. We compute axis deltas
    for each module separately, combine with module-dominance logic,
    then match against all 8 profiles via cosine similarity.

    Returns: {
      answered_count (total non-null),
      fiction_answered, nonfiction_answered,
      axis_scores (combined, used for profile matching),
      fiction_axis_scores, nonfiction_axis_scores (for UI split),
      dominant_module ("fiction" | "nonfiction" | "both"),
      profiles (top 2 by similarity),
      has_enough_data,
      note (explanatory sentence about which module drove the result),
    }
    """
    fiction_by_order = {b["order"]: b for b in FICTION}
    nonfiction_by_order = {b["order"]: b for b in NONFICTION}

    fiction_axes = {k: 0.0 for k in FICTION_AXIS_KEYS}
    nonfiction_axes = {k: 0.0 for k in AXIS_KEYS}
    fiction_count = 0
    nonfiction_count = 0

    for r in responses:
        value = r.get("value")
        if value is None:
            continue
        module = r.get("module")
        order = r.get("order")
        if module == "fiction":
            item = fiction_by_order.get(order)
            if not item:
                continue
            fiction_count += 1
            for axis, weight in item["weights"].items():
                if axis in fiction_axes:
                    fiction_axes[axis] += weight * value
        elif module == "nonfiction":
            item = nonfiction_by_order.get(order)
            if not item:
                continue
            nonfiction_count += 1
            for axis, weight in item["weights"].items():
                if axis in nonfiction_axes:
                    nonfiction_axes[axis] += weight * value

    total = fiction_count + nonfiction_count
    fiction_ok = fiction_count >= FICTION_MIN
    nonfiction_ok = nonfiction_count >= NONFICTION_MIN

    # Not enough in either module
    if not fiction_ok and not nonfiction_ok:
        return {
            "answered_count": total,
            "fiction_answered": fiction_count,
            "nonfiction_answered": nonfiction_count,
            "axis_scores": {k: 0.0 for k in AXIS_KEYS},
            "fiction_axis_scores": fiction_axes,
            "nonfiction_axis_scores": nonfiction_axes,
            "profiles": [],
            "has_enough_data": False,
            "dominant_module": None,
            "note": f"Answer at least {FICTION_MIN} fiction titles or {NONFICTION_MIN} nonfiction titles to see your reader profile.",
        }

    # Decide which module(s) to use
    use_fiction = fiction_ok
    use_nonfiction = nonfiction_count >= NONFICTION_MIN_TO_USE

    combined: dict[str, float] = {k: 0.0 for k in AXIS_KEYS}
    if use_fiction:
        for k, v in fiction_axes.items():
            combined[k] += v
    if use_nonfiction:
        for k, v in nonfiction_axes.items():
            combined[k] += v

    # Module dominance: which module's axis vector has more magnitude?
    fiction_mag = math.sqrt(sum(v * v for v in fiction_axes.values()))
    nonfiction_mag = math.sqrt(sum(v * v for v in nonfiction_axes.values()))
    if use_fiction and use_nonfiction:
        if fiction_mag > nonfiction_mag * 1.3:
            dominant = "fiction"
            note = "Your fiction taste is driving this result."
        elif nonfiction_mag > fiction_mag * 1.3:
            dominant = "nonfiction"
            note = "Your nonfiction taste is driving this result."
        else:
            dominant = "both"
            note = "Both modules are pulling on the result evenly."
    elif use_fiction:
        dominant = "fiction"
        note = "Your fiction taste is driving this result — you haven't rated enough nonfiction yet to know that side."
    else:
        dominant = "nonfiction"
        note = "Your nonfiction taste is driving this result — rate more fiction to round this out."

    # Cosine similarity against profiles
    user_vec = [combined[k] for k in AXIS_KEYS]
    norm_u = math.sqrt(sum(v * v for v in user_vec))
    ranked: list[dict] = []
    for profile in PROFILES:
        profile_vec = [profile["vector"].get(k, 0.0) for k in AXIS_KEYS]
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
        "answered_count": total,
        "fiction_answered": fiction_count,
        "nonfiction_answered": nonfiction_count,
        "axis_scores": combined,
        "fiction_axis_scores": fiction_axes,
        "nonfiction_axis_scores": nonfiction_axes,
        "profiles": ranked[:2],
        "has_enough_data": True,
        "dominant_module": dominant,
        "note": note,
    }
