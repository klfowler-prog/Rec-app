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

# 24 shows in presentation order. `years` is a string like "2011-2019"
# or "2022-" for still-airing — TMDB's first_air_date only gives us
# the start year, so we pass a `tmdb_year` hint for the TMDB lookup
# and a `years` display string for the UI. `weights` are the axis
# deltas applied when the user rates this show. `generation` and
# `scenes` are Phase D2 tags used by the taste-quiz endpoint to
# filter the pool against the user's saved onboarding picks.
SHOWS: list[dict] = [
    {"order": 1,  "title": "Friends",              "tmdb_year": 1994, "years": "1994–2004",
     "weights": {"emotional": 2, "irony": -2, "ambiguity": -1},
     "generation": ["classic", "millennial", "universal"],
     "scenes": ["comedy", "romance"]},
    {"order": 2,  "title": "The Office",           "tmdb_year": 2005, "years": "2005–2013",
     "weights": {"comedy": 1, "emotional": 1, "irony": 1},
     "generation": ["millennial", "universal"],
     "scenes": ["comedy"]},
    {"order": 3,  "title": "Schitt's Creek",       "tmdb_year": 2015, "years": "2015–2020",
     "weights": {"emotional": 2, "darkness": -2, "irony": -1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["comedy"]},
    {"order": 4,  "title": "Abbott Elementary",    "tmdb_year": 2021, "years": "2021–",
     "weights": {"emotional": 1, "comedy": 1, "irony": -1, "darkness": -1},
     "generation": ["gen_z"],
     "scenes": ["comedy"]},
    {"order": 5,  "title": "Game of Thrones",      "tmdb_year": 2011, "years": "2011–2019",
     "weights": {"genre": 1, "darkness": 1, "serialization": 1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["scifi_fantasy", "prestige_drama"]},
    {"order": 6,  "title": "Breaking Bad",         "tmdb_year": 2008, "years": "2008–2013",
     "weights": {"darkness": 2, "moral_ambiguity": 2, "serialization": 1},
     "generation": ["millennial", "universal"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 7,  "title": "Black Mirror",         "tmdb_year": 2011, "years": "2011–",
     "weights": {"darkness": 2, "genre": 1, "ambiguity": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["scifi_fantasy", "prestige_drama"]},
    {"order": 8,  "title": "Seinfeld",             "tmdb_year": 1989, "years": "1989–1998",
     "weights": {"irony": 2, "emotional": -2, "comedy": 1, "moral_ambiguity": 1},
     "generation": ["classic"],
     "scenes": ["comedy"]},
    {"order": 9,  "title": "Succession",           "tmdb_year": 2018, "years": "2018–2023",
     "weights": {"irony": 2, "moral_ambiguity": 2, "darkness": 1, "emotional": -1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["prestige_drama", "comedy"]},
    {"order": 10, "title": "Arrested Development", "tmdb_year": 2003, "years": "2003–2019",
     "weights": {"comedy": 2, "irony": 1, "serialization": 1, "emotional": -1},
     "generation": ["millennial"],
     "scenes": ["comedy"]},
    {"order": 11, "title": "Family Guy",           "tmdb_year": 1999, "years": "1999–",
     "weights": {"comedy": 2, "irony": 1, "genre": 1, "emotional": -2},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["comedy"]},
    {"order": 12, "title": "Fleabag",              "tmdb_year": 2016, "years": "2016–2019",
     "weights": {"emotional": 2, "comedy": 1, "irony": 1, "ambiguity": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["comedy", "prestige_drama", "indie_arthouse"]},
    {"order": 13, "title": "Mad Men",              "tmdb_year": 2007, "years": "2007–2015",
     "weights": {"serialization": 2, "moral_ambiguity": 1, "ambiguity": 1, "emotional": 1},
     "generation": ["millennial"],
     "scenes": ["prestige_drama"]},
    {"order": 14, "title": "The Sopranos",         "tmdb_year": 1999, "years": "1999–2007",
     "weights": {"moral_ambiguity": 2, "serialization": 2, "darkness": 1},
     "generation": ["millennial", "universal"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 15, "title": "The Wire",             "tmdb_year": 2002, "years": "2002–2008",
     "weights": {"serialization": 2, "moral_ambiguity": 1, "darkness": 1, "ambiguity": 1},
     "generation": ["millennial"],
     "scenes": ["action_thriller", "prestige_drama", "true_crime"]},
    {"order": 16, "title": "The Bear",             "tmdb_year": 2022, "years": "2022–",
     "weights": {"darkness": 1, "emotional": 1, "ambiguity": 1},
     "generation": ["gen_z"],
     "scenes": ["prestige_drama", "comedy"]},
    {"order": 17, "title": "True Detective",       "tmdb_year": 2014, "years": "2014",
     "weights": {"darkness": 2, "ambiguity": 2, "moral_ambiguity": 1, "serialization": 1},
     "generation": ["millennial"],
     "scenes": ["true_crime", "action_thriller", "prestige_drama", "horror"]},
    {"order": 18, "title": "Severance",            "tmdb_year": 2022, "years": "2022–",
     "weights": {"ambiguity": 2, "genre": 1, "serialization": 1, "darkness": 1},
     "generation": ["gen_z"],
     "scenes": ["scifi_fantasy", "prestige_drama"]},
    {"order": 19, "title": "The Leftovers",        "tmdb_year": 2014, "years": "2014–2017",
     "weights": {"ambiguity": 2, "emotional": 2, "darkness": 2, "genre": 1},
     "generation": ["millennial"],
     "scenes": ["scifi_fantasy", "prestige_drama", "indie_arthouse"]},
    # Additional items to broaden surface area — warm earnest
    # comfort, absurdist animation, international genre thriller,
    # workplace sitcom, and prestige royal drama.
    {"order": 20, "title": "Ted Lasso",             "tmdb_year": 2020, "years": "2020–2023",
     "weights": {"emotional": 2, "irony": -2, "darkness": -2},
     "generation": ["gen_z"],
     "scenes": ["comedy", "sports"]},
    {"order": 21, "title": "Brooklyn Nine-Nine",    "tmdb_year": 2013, "years": "2013–2021",
     "weights": {"comedy": 1, "emotional": 1, "irony": -1, "darkness": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["comedy"]},
    {"order": 22, "title": "Rick and Morty",        "tmdb_year": 2013, "years": "2013–",
     "weights": {"comedy": 2, "irony": 2, "ambiguity": 1, "darkness": 1, "emotional": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["comedy", "scifi_fantasy"]},
    {"order": 23, "title": "Squid Game",            "tmdb_year": 2021, "years": "2021–",
     "weights": {"genre": 1, "darkness": 2, "serialization": 1, "moral_ambiguity": 1},
     "generation": ["gen_z", "universal"],
     "scenes": ["k_content", "action_thriller", "prestige_drama"]},
    {"order": 24, "title": "The Crown",             "tmdb_year": 2016, "years": "2016–2023",
     "weights": {"serialization": 2, "emotional": 1, "moral_ambiguity": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["prestige_drama", "romance"]},
    # Anime (Phase D3a) — the shonen/seinen anchors plus the
    # acknowledged adult-crossover canon. The son's primary scene.
    {"order": 25, "title": "Demon Slayer",              "tmdb_year": 2019, "years": "2019–",
     "weights": {"genre": 2, "darkness": 1, "emotional": 1, "serialization": 1},
     "generation": ["gen_z"],
     "scenes": ["anime", "action_thriller"]},
    {"order": 26, "title": "Attack on Titan",           "tmdb_year": 2013, "years": "2013–2023",
     "weights": {"genre": 2, "darkness": 2, "moral_ambiguity": 2, "serialization": 2},
     "generation": ["millennial", "gen_z"],
     "scenes": ["anime", "action_thriller", "scifi_fantasy"]},
    {"order": 27, "title": "Jujutsu Kaisen",            "tmdb_year": 2020, "years": "2020–",
     "weights": {"genre": 2, "darkness": 1, "serialization": 1},
     "generation": ["gen_z"],
     "scenes": ["anime", "action_thriller"]},
    {"order": 28, "title": "My Hero Academia",          "tmdb_year": 2016, "years": "2016–",
     "weights": {"genre": 1, "emotional": 1, "serialization": 1, "darkness": -1},
     "generation": ["gen_z"],
     "scenes": ["anime", "action_thriller"]},
    {"order": 29, "title": "Naruto",                    "tmdb_year": 2002, "years": "2002–2017",
     "weights": {"genre": 1, "emotional": 1, "serialization": 2, "darkness": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["anime", "action_thriller"]},
    {"order": 30, "title": "Death Note",                "tmdb_year": 2006, "years": "2006–2007",
     "weights": {"genre": 2, "moral_ambiguity": 2, "darkness": 1, "serialization": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["anime", "action_thriller", "prestige_drama"]},
    {"order": 31, "title": "Cowboy Bebop",              "tmdb_year": 1998, "years": "1998–1999",
     "weights": {"genre": 2, "ambiguity": 1, "irony": 1, "serialization": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["anime", "scifi_fantasy", "indie_arthouse"]},
    {"order": 32, "title": "Fullmetal Alchemist: Brotherhood", "tmdb_year": 2009, "years": "2009–2010",
     "weights": {"genre": 2, "emotional": 1, "moral_ambiguity": 1, "serialization": 2},
     "generation": ["millennial", "gen_z"],
     "scenes": ["anime", "action_thriller", "prestige_drama"]},
    {"order": 33, "title": "Spy x Family",              "tmdb_year": 2022, "years": "2022–",
     "weights": {"comedy": 1, "emotional": 1, "genre": 1},
     "generation": ["gen_z"],
     "scenes": ["anime", "comedy", "action_thriller"]},
    # Gaming culture (Phase D3a) — the bridge between gaming fandoms
    # and the TV/streaming content those fandoms actually watch.
    {"order": 34, "title": "Arcane",                    "tmdb_year": 2021, "years": "2021–",
     "weights": {"genre": 2, "darkness": 1, "emotional": 1, "serialization": 1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "action_thriller", "scifi_fantasy"]},
    {"order": 35, "title": "The Last of Us",            "tmdb_year": 2023, "years": "2023–",
     "weights": {"darkness": 2, "emotional": 2, "moral_ambiguity": 1, "serialization": 1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "action_thriller", "horror"]},
    {"order": 36, "title": "Castlevania",               "tmdb_year": 2017, "years": "2017–2021",
     "weights": {"genre": 2, "darkness": 2, "serialization": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["gaming_culture", "action_thriller", "scifi_fantasy", "horror"]},
    {"order": 37, "title": "Cyberpunk: Edgerunners",    "tmdb_year": 2022, "years": "2022",
     "weights": {"darkness": 2, "genre": 2, "emotional": 1, "moral_ambiguity": 1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "anime", "action_thriller", "scifi_fantasy"]},
    {"order": 38, "title": "Fallout",                   "tmdb_year": 2024, "years": "2024–",
     "weights": {"genre": 2, "darkness": 1, "irony": 1, "serialization": 1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "scifi_fantasy", "action_thriller"]},
    # Action + thrillers (Phase D3b) — husband's primary TV scene.
    # The existing pool had Breaking Bad, The Sopranos, The Wire,
    # and Squid Game but was thin on contemporary thriller series.
    {"order": 39, "title": "Reacher",                    "tmdb_year": 2022, "years": "2022–",
     "weights": {"genre": 1, "darkness": 1},
     "generation": ["gen_z"],
     "scenes": ["action_thriller"]},
    {"order": 40, "title": "Slow Horses",                "tmdb_year": 2022, "years": "2022–",
     "weights": {"genre": 1, "darkness": 1, "moral_ambiguity": 1, "serialization": 1},
     "generation": ["gen_z"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 41, "title": "Jack Ryan",                  "tmdb_year": 2018, "years": "2018–2023",
     "weights": {"genre": 1, "serialization": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["action_thriller"]},
    {"order": 42, "title": "The Boys",                   "tmdb_year": 2019, "years": "2019–",
     "weights": {"genre": 2, "darkness": 2, "moral_ambiguity": 2, "irony": 2},
     "generation": ["gen_z"],
     "scenes": ["action_thriller", "scifi_fantasy", "comedy"]},
    # Comedies (Phase D3b) — workplace + absurdist + ensemble.
    # The existing pool had The Office, Schitt's Creek, Abbott
    # Elementary, Seinfeld, and Brooklyn Nine-Nine but was missing
    # the key absurdist + horror-comedy + Parks-and-Rec-style
    # ensemble anchors.
    {"order": 43, "title": "Parks and Recreation",       "tmdb_year": 2009, "years": "2009–2015",
     "weights": {"comedy": 1, "emotional": 2, "irony": -1, "darkness": -2},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["comedy"]},
    {"order": 44, "title": "What We Do in the Shadows",  "tmdb_year": 2019, "years": "2019–2024",
     "weights": {"comedy": 2, "irony": 2, "genre": 1},
     "generation": ["gen_z"],
     "scenes": ["comedy", "horror"]},
    {"order": 45, "title": "It's Always Sunny in Philadelphia", "tmdb_year": 2005, "years": "2005–",
     "weights": {"comedy": 2, "irony": 2, "moral_ambiguity": 2, "darkness": 1, "emotional": -2},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["comedy"]},
    {"order": 46, "title": "30 Rock",                    "tmdb_year": 2006, "years": "2006–2013",
     "weights": {"comedy": 2, "irony": 2, "emotional": 1},
     "generation": ["millennial"],
     "scenes": ["comedy"]},
]


PROFILES: list[dict] = [
    {
        "id": "long_game_player",
        "name": "The Long Game Player",
        "vector": {"serialization": 1.0, "moral_ambiguity": 1.0, "darkness": 1.0},
        "description": "You treat TV as the medium's truest form. Patience is a prerequisite, not a sacrifice. You commit to slow-build dramas that trust you to follow a long arc, and you're rewarded for staying with them.",
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
        "description": "Character is everything. You're not looking to be provoked — you're looking to recognize something true. You're drawn to shows that trust small moments and earn their feelings.",
    },
    {
        "id": "comfortable_rewatcher",
        "name": "The Comfortable Rewatcher",
        "vector": {"emotional": 1.0, "serialization": -1.0, "darkness": -1.0},
        "description": "You know what you like and you return to it. TV is pleasure, not a commitment or a challenge. You want warmth, familiarity, and stories that leave you lighter than they found you.",
    },
    {
        "id": "ambiguity_seeker",
        "name": "The Ambiguity Seeker",
        "vector": {"ambiguity": 1.0, "genre": 1.0, "emotional": -0.5},
        "description": "You want TV to destabilize, not reassure. You're drawn to shows that withhold answers, shift reality, or leave you uncertain about what you just watched.",
    },
    {
        "id": "prestige_convert",
        "name": "The Prestige Convert",
        "vector": {"serialization": 1.0, "moral_ambiguity": 1.0, "emotional": 0.3},
        "description": "You think of the best dramas in the same breath as great novels. You want craft, patience, and long-form storytelling that pays off character work episode by episode.",
    },
]


# Below the movie quiz threshold because there are 19 shows, not 20,
# and TV taste tends to be more hybrid than film taste so we want to
# surface a profile slightly earlier.
MIN_ANSWERED = 8


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
