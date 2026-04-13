"""TV taste quiz — static data only.

19-question quiz that scores the user on 8 TV-specific taste axes.
TV axes differ from movies — serialization tolerance and moral
ambiguity comfort are distinct dimensions that matter much more in
long-form television than in film. See the spec for the axis list.

Shows are presented in a deliberate accessible → challenging order.
Do NOT randomize. Shows with a null response are excluded from
scoring entirely.

Scoring logic lives in taste_quiz_scoring.py — this module is data.
"""

from app.services.taste_quiz_scoring import score_responses as _score

# 8 TV-specific axes. serialization and moral_ambiguity replace the
# movie-quiz's pace and film_history — long-form TV's distinguishing
# dimensions are "will you commit to a slow build" and "can you
# invest in genuinely bad people without needing someone to root for".
AXES: list[dict] = [
    {"key": "serialization",   "label": "Serialization Tolerance", "description": "Commits to long-arc payoff over episodic closure"},
    {"key": "darkness",        "label": "Darkness Tolerance",      "description": "Engages bleak or punishing material"},
    {"key": "moral_ambiguity", "label": "Moral Ambiguity Comfort", "description": "Can invest in genuinely bad people"},
    {"key": "emotional",       "label": "Emotional Register",      "description": "Immersive, character-driven engagement"},
    {"key": "irony",           "label": "Irony Index",             "description": "Detached, deadpan, self-aware"},
    {"key": "comedy",          "label": "Comedy Register",         "description": "Absurdist, transgressive, dark"},
    {"key": "genre",           "label": "Genre Openness",          "description": "Uses genre as a tool, not a filter"},
    {"key": "ambiguity",       "label": "Ambiguity Comfort",       "description": "Surreal, unresolved, unexplained"},
]

AXIS_KEYS: list[str] = [a["key"] for a in AXES]

# Response options — identical to the movie quiz.
RESPONSE_OPTIONS: list[dict] = [
    {"value": 2,    "emoji": "❤️",   "label": "Loved it",        "description": "A real favorite"},
    {"value": 1,    "emoji": "👍",   "label": "Liked it",        "description": "Enjoyed it"},
    {"value": 0,    "emoji": "😐",   "label": "It's fine",       "description": "Neutral"},
    {"value": -1,   "emoji": "👎",   "label": "Didn't click",    "description": "Not for me"},
    {"value": None, "emoji": "🚫",   "label": "Haven't seen it", "description": "Skip"},
]

RATING_MAP: dict[int, int] = {2: 9, 1: 7, 0: 5, -1: 3}

# 19 shows in presentation order. `years` is a string like "2011-2019"
# or "2022-" for still-airing — TMDB's first_air_date only gives us
# the start year, so we pass a `tmdb_year` hint for the TMDB lookup
# and a `years` display string for the UI. `weights` are the axis
# deltas applied when the user rates this show.
SHOWS: list[dict] = [
    {"order": 1,  "title": "Friends",              "tmdb_year": 1994, "years": "1994–2004",
     "weights": {"emotional": 2, "irony": -2, "ambiguity": -1}},
    {"order": 2,  "title": "The Office",           "tmdb_year": 2005, "years": "2005–2013",
     "weights": {"comedy": 1, "emotional": 1, "irony": 1}},
    {"order": 3,  "title": "Schitt's Creek",       "tmdb_year": 2015, "years": "2015–2020",
     "weights": {"emotional": 2, "darkness": -2, "irony": -1}},
    {"order": 4,  "title": "Abbott Elementary",    "tmdb_year": 2021, "years": "2021–",
     "weights": {"emotional": 1, "comedy": 1, "irony": -1, "darkness": -1}},
    {"order": 5,  "title": "Game of Thrones",      "tmdb_year": 2011, "years": "2011–2019",
     "weights": {"genre": 1, "darkness": 1, "serialization": 1}},
    {"order": 6,  "title": "Breaking Bad",         "tmdb_year": 2008, "years": "2008–2013",
     "weights": {"darkness": 2, "moral_ambiguity": 2, "serialization": 1}},
    {"order": 7,  "title": "Black Mirror",         "tmdb_year": 2011, "years": "2011–",
     "weights": {"darkness": 2, "genre": 1, "ambiguity": 1}},
    {"order": 8,  "title": "Seinfeld",             "tmdb_year": 1989, "years": "1989–1998",
     "weights": {"irony": 2, "emotional": -2, "comedy": 1, "moral_ambiguity": 1}},
    {"order": 9,  "title": "Succession",           "tmdb_year": 2018, "years": "2018–2023",
     "weights": {"irony": 2, "moral_ambiguity": 2, "darkness": 1, "emotional": -1}},
    {"order": 10, "title": "Arrested Development", "tmdb_year": 2003, "years": "2003–2019",
     "weights": {"comedy": 2, "irony": 1, "serialization": 1, "emotional": -1}},
    {"order": 11, "title": "Family Guy",           "tmdb_year": 1999, "years": "1999–",
     "weights": {"comedy": 2, "irony": 1, "genre": 1, "emotional": -2}},
    {"order": 12, "title": "Fleabag",              "tmdb_year": 2016, "years": "2016–2019",
     "weights": {"emotional": 2, "comedy": 1, "irony": 1, "ambiguity": 1}},
    {"order": 13, "title": "Mad Men",              "tmdb_year": 2007, "years": "2007–2015",
     "weights": {"serialization": 2, "moral_ambiguity": 1, "ambiguity": 1, "emotional": 1}},
    {"order": 14, "title": "The Sopranos",         "tmdb_year": 1999, "years": "1999–2007",
     "weights": {"moral_ambiguity": 2, "serialization": 2, "darkness": 1}},
    {"order": 15, "title": "The Wire",             "tmdb_year": 2002, "years": "2002–2008",
     "weights": {"serialization": 2, "moral_ambiguity": 1, "darkness": 1, "ambiguity": 1}},
    {"order": 16, "title": "The Bear",             "tmdb_year": 2022, "years": "2022–",
     "weights": {"darkness": 1, "emotional": 1, "ambiguity": 1}},
    {"order": 17, "title": "True Detective",       "tmdb_year": 2014, "years": "2014",
     "weights": {"darkness": 2, "ambiguity": 2, "moral_ambiguity": 1, "serialization": 1}},
    {"order": 18, "title": "Severance",            "tmdb_year": 2022, "years": "2022–",
     "weights": {"ambiguity": 2, "genre": 1, "serialization": 1, "darkness": 1}},
    {"order": 19, "title": "The Leftovers",        "tmdb_year": 2014, "years": "2014–2017",
     "weights": {"ambiguity": 2, "emotional": 2, "darkness": 2, "genre": 1}},
]


PROFILES: list[dict] = [
    {
        "id": "long_game_player",
        "name": "The Long Game Player",
        "vector": {"serialization": 1.0, "moral_ambiguity": 1.0, "darkness": 1.0},
        "description": "You treat TV as the medium's truest form. Patience is a prerequisite, not a sacrifice. The Sopranos, The Wire, and Breaking Bad reward the commitment they demand.",
    },
    {
        "id": "dark_comedy_devotee",
        "name": "The Dark Comedy Devotee",
        "vector": {"irony": 1.0, "comedy": 1.0, "moral_ambiguity": 1.0},
        "description": "Warmth makes you suspicious. You want wit, transgression, and no one to root for — and you find that more honest than sentimentality.",
    },
    {
        "id": "emotionally_invested",
        "name": "The Emotionally Invested",
        "vector": {"emotional": 1.0, "irony": -1.0, "darkness": -0.5},
        "description": "Character is everything. You're not looking to be provoked — you're looking to recognize something true. Fleabag, Schitt's Creek, The Bear.",
    },
    {
        "id": "comfortable_rewatcher",
        "name": "The Comfortable Rewatcher",
        "vector": {"emotional": 1.0, "serialization": -1.0, "darkness": -1.0},
        "description": "You know what you like and you return to it. TV is pleasure, not a commitment or a challenge. Friends, The Office, Abbott Elementary.",
    },
    {
        "id": "ambiguity_seeker",
        "name": "The Ambiguity Seeker",
        "vector": {"ambiguity": 1.0, "genre": 1.0, "emotional": -0.5},
        "description": "You want TV to destabilize, not reassure. Severance, The Leftovers, True Detective — shows that leave you uncertain about what you just watched.",
    },
    {
        "id": "prestige_convert",
        "name": "The Prestige Convert",
        "vector": {"serialization": 1.0, "moral_ambiguity": 1.0, "emotional": 0.3},
        "description": "You think of the best dramas in the same breath as great novels. The Sopranos, Mad Men, The Wire — long-form storytelling at the level of literature.",
    },
]


# Below the movie quiz threshold because there are 19 shows, not 20,
# and TV taste tends to be more hybrid than film taste so we want to
# surface a profile slightly earlier.
MIN_ANSWERED = 10


def score_responses(responses: list[dict]) -> dict:
    """Score quiz responses against the TV data. Thin wrapper that
    delegates the actual math to taste_quiz_scoring._score."""
    return _score(
        responses=responses,
        items=SHOWS,
        axis_keys=AXIS_KEYS,
        profiles=PROFILES,
        min_answered=MIN_ANSWERED,
    )
