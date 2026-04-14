"""Movie taste quiz — static data only.

20-question quiz that scores the user on 8 taste axes and surfaces a
direction-blend (top 2 profile matches) rather than pinning them to a
single label. The axis scores themselves are the real signal; profile
labels are shorthand for the user-facing description and for feeding
into recommendation prompts as a hint.

Films are presented in a deliberate accessible → challenging order.
Do NOT randomize. Films with a null response are excluded from
scoring entirely.

Scoring logic lives in taste_quiz_scoring.py — this module is data.
"""

from app.services.taste_quiz_scoring import score_responses as _score

# 8 axes with short keys + human labels used in the UI.
AXES: list[dict] = [
    {"key": "pace",         "label": "Pace Tolerance",     "description": "Comfort with slow, contemplative films"},
    {"key": "darkness",     "label": "Darkness Tolerance", "description": "Engages nihilistic or punishing material"},
    {"key": "ambiguity",    "label": "Ambiguity Comfort",  "description": "Prefers open endings, unresolved questions"},
    {"key": "emotional",    "label": "Emotional Register", "description": "Drawn to character and emotional truth"},
    {"key": "irony",        "label": "Irony Index",        "description": "Deadpan, meta, detached humor"},
    {"key": "comedy",       "label": "Comedy Register",    "description": "Absurdist or formally inventive comedy"},
    {"key": "genre",        "label": "Genre Openness",     "description": "Uses genre as a tool, not a filter"},
    {"key": "film_history", "label": "Film History",       "description": "Engages cinema as a tradition"},
]

AXIS_KEYS: list[str] = [a["key"] for a in AXES]

# Response options — value is what gets multiplied against the film's
# axis weight when scoring. null means "haven't seen" and is excluded
# from the math entirely (not treated as 0).
RESPONSE_OPTIONS: list[dict] = [
    {"value": 2,    "emoji": "❤️",   "label": "Loved it",       "description": "A real favorite"},
    {"value": 1,    "emoji": "👍",   "label": "Liked it",       "description": "Enjoyed it"},
    {"value": 0,    "emoji": "😐",   "label": "It's fine",      "description": "Neutral"},
    {"value": -1,   "emoji": "👎",   "label": "Didn't click",   "description": "Not for me"},
    {"value": None, "emoji": "🚫",   "label": "Haven't seen it","description": "Skip"},
]

# Map quiz response values to a 1-10 rating we can persist in the
# user's profile so the existing recommendation pipeline sees the
# signal too.
RATING_MAP: dict[int, int] = {2: 9, 1: 7, 0: 5, -1: 3}


# 25 films in presentation order. `weights` are the axis deltas
# applied when the user rates this film (multiplied by the response
# value). `generation` and `scenes` are Phase D2 tags used by the
# taste-quiz endpoint to filter the pool against the user's saved
# onboarding picks — a film that matches neither the user's generation
# nor their scene picks is dropped before render. See Part 4 of the
# plan for the vocabulary. Accessible → challenging ordering is
# intentional.
FILMS: list[dict] = [
    {"order": 1,  "title": "Groundhog Day",                          "year": 1993,
     "weights": {"comedy": 1, "emotional": 1},
     "generation": ["classic", "universal"],
     "scenes": ["comedy", "romance", "scifi_fantasy"]},
    {"order": 2,  "title": "Pulp Fiction",                           "year": 1994,
     "weights": {"ambiguity": 1, "irony": 1, "darkness": 1, "genre": 1},
     "generation": ["classic", "universal"],
     "scenes": ["action_thriller", "prestige_drama", "indie_arthouse"]},
    {"order": 3,  "title": "La La Land",                             "year": 2016,
     "weights": {"irony": -2, "darkness": -1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["romance", "music", "prestige_drama"]},
    {"order": 4,  "title": "The Dark Knight",                        "year": 2008,
     "weights": {"genre": 1, "darkness": 1, "irony": -1},
     "generation": ["millennial", "universal"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 5,  "title": "Get Out",                                "year": 2017,
     "weights": {"genre": 2, "darkness": 1, "emotional": 1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["horror", "prestige_drama"]},
    {"order": 6,  "title": "Arrival",                                "year": 2016,
     "weights": {"emotional": 1, "genre": 1, "pace": 1, "ambiguity": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["scifi_fantasy", "prestige_drama", "indie_arthouse"]},
    {"order": 7,  "title": "Eternal Sunshine of the Spotless Mind",  "year": 2004,
     "weights": {"emotional": 2, "ambiguity": 1, "genre": 1},
     "generation": ["millennial"],
     "scenes": ["romance", "scifi_fantasy", "indie_arthouse"]},
    {"order": 8,  "title": "Airplane!",                              "year": 1980,
     "weights": {"comedy": 2, "irony": 1, "emotional": -2},
     "generation": ["classic"],
     "scenes": ["comedy"]},
    {"order": 9,  "title": "Parasite",                               "year": 2019,
     "weights": {"genre": 2, "ambiguity": 1, "darkness": 1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["k_content", "prestige_drama", "action_thriller"]},
    {"order": 10, "title": "Mad Max: Fury Road",                     "year": 2015,
     "weights": {"pace": -2, "ambiguity": -1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["action_thriller", "scifi_fantasy"]},
    {"order": 11, "title": "The Shining",                            "year": 1980,
     "weights": {"darkness": 1, "ambiguity": 1, "film_history": 1, "genre": 1},
     "generation": ["classic", "universal"],
     "scenes": ["horror", "prestige_drama"]},
    {"order": 12, "title": "Annie Hall",                             "year": 1977,
     "weights": {"comedy": 2, "irony": 1, "emotional": 1, "film_history": 1},
     "generation": ["classic"],
     "scenes": ["comedy", "romance", "prestige_drama", "indie_arthouse"]},
    {"order": 13, "title": "No Country for Old Men",                 "year": 2007,
     "weights": {"ambiguity": 2, "darkness": 2},
     "generation": ["millennial"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 14, "title": "Marriage Story",                         "year": 2019,
     "weights": {"emotional": 2, "irony": -1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 15, "title": "Raising Arizona",                        "year": 1987,
     "weights": {"comedy": 1, "irony": 1, "emotional": 1, "film_history": 1},
     "generation": ["classic"],
     "scenes": ["comedy", "indie_arthouse"]},
    {"order": 16, "title": "The Big Lebowski",                       "year": 1998,
     "weights": {"irony": 2, "ambiguity": 1, "comedy": 1},
     "generation": ["millennial", "universal"],
     "scenes": ["comedy", "indie_arthouse"]},
    {"order": 17, "title": "Chinatown",                              "year": 1974,
     "weights": {"darkness": 2, "ambiguity": 2, "film_history": 2},
     "generation": ["classic"],
     "scenes": ["action_thriller", "prestige_drama", "indie_arthouse"]},
    {"order": 18, "title": "There Will Be Blood",                    "year": 2007,
     "weights": {"pace": 2, "darkness": 1, "emotional": -1},
     "generation": ["millennial"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 19, "title": "Apocalypse Now",                         "year": 1979,
     "weights": {"film_history": 2, "pace": 2, "darkness": 2},
     "generation": ["classic"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 20, "title": "2001: A Space Odyssey",                  "year": 1968,
     "weights": {"pace": 2, "ambiguity": 2, "film_history": 1},
     "generation": ["classic"],
     "scenes": ["scifi_fantasy", "indie_arthouse"]},
    # Additional mainstream/canonical items to give users a bigger
    # surface to find things they've actually seen. Span comedy,
    # romance, action, classic prestige, and coming-of-age so the
    # axis probes stay balanced.
    {"order": 21, "title": "Toy Story",                              "year": 1995,
     "weights": {"emotional": 1, "comedy": 1, "darkness": -2},
     "generation": ["classic", "millennial", "gen_z", "universal"],
     "scenes": ["kids_family", "comedy"]},
    {"order": 22, "title": "When Harry Met Sally",                   "year": 1989,
     "weights": {"emotional": 1, "comedy": 1, "irony": 1},
     "generation": ["classic"],
     "scenes": ["romance", "comedy"]},
    {"order": 23, "title": "The Godfather",                          "year": 1972,
     "weights": {"film_history": 2, "pace": 1, "darkness": 1, "emotional": 1},
     "generation": ["classic", "universal"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 24, "title": "John Wick",                              "year": 2014,
     "weights": {"genre": 1, "pace": -2, "darkness": 1, "emotional": -1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["action_thriller"]},
    {"order": 25, "title": "Boyhood",                                "year": 2014,
     "weights": {"pace": 2, "emotional": 1, "ambiguity": 1},
     "generation": ["millennial"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    # Anime (Phase D3a) — Studio Ghibli anchors plus recent shōnen
    # theatrical hits a gen_z teen would plausibly know. Covers the
    # son's primary scene.
    {"order": 26, "title": "Spirited Away",                           "year": 2001,
     "weights": {"emotional": 2, "genre": 2, "film_history": 1, "ambiguity": 1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["anime", "kids_family", "indie_arthouse"]},
    {"order": 27, "title": "My Neighbor Totoro",                      "year": 1988,
     "weights": {"emotional": 2, "genre": 1, "darkness": -2, "film_history": 1},
     "generation": ["classic", "millennial", "universal"],
     "scenes": ["anime", "kids_family"]},
    {"order": 28, "title": "Princess Mononoke",                       "year": 1997,
     "weights": {"emotional": 1, "genre": 2, "darkness": 1, "ambiguity": 1},
     "generation": ["millennial", "universal"],
     "scenes": ["anime", "scifi_fantasy"]},
    {"order": 29, "title": "Akira",                                   "year": 1988,
     "weights": {"genre": 2, "darkness": 2, "ambiguity": 1, "film_history": 1},
     "generation": ["classic"],
     "scenes": ["anime", "scifi_fantasy", "indie_arthouse"]},
    {"order": 30, "title": "Your Name",                               "year": 2016,
     "weights": {"emotional": 2, "genre": 1, "ambiguity": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["anime", "romance", "scifi_fantasy"]},
    {"order": 31, "title": "Demon Slayer: Mugen Train",               "year": 2020,
     "weights": {"genre": 2, "emotional": 1, "darkness": 1},
     "generation": ["gen_z"],
     "scenes": ["anime", "action_thriller"]},
    {"order": 32, "title": "A Silent Voice",                          "year": 2016,
     "weights": {"emotional": 2, "ambiguity": 1, "darkness": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["anime", "romance", "prestige_drama"]},
    # Gaming culture (Phase D3a) — films that spawned from games /
    # game franchises. The bridge for users who engage with gaming-
    # adjacent media but don't (yet) have a games tracker in the app.
    {"order": 33, "title": "Five Nights at Freddy's",                 "year": 2023,
     "weights": {"genre": 1, "darkness": 1, "emotional": -1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "horror"]},
    {"order": 34, "title": "The Super Mario Bros. Movie",             "year": 2023,
     "weights": {"genre": 1, "emotional": 1, "darkness": -2},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "kids_family"]},
    {"order": 35, "title": "Sonic the Hedgehog",                      "year": 2020,
     "weights": {"genre": 1, "emotional": 1, "darkness": -2, "comedy": 1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "kids_family", "action_thriller"]},
    {"order": 36, "title": "Detective Pikachu",                       "year": 2019,
     "weights": {"genre": 1, "emotional": 1, "comedy": 1, "darkness": -1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["gaming_culture", "kids_family", "action_thriller"]},
    # Action / thrillers (Phase D3b) — mainstream genre cinema, the
    # husband's primary scene. The existing pool had some strong
    # action anchors (Dark Knight, John Wick, Mad Max, Parasite)
    # but lacked the spy thriller + buddy-cop + old-school action
    # canon a genre fan would actually recognize.
    {"order": 37, "title": "Mission: Impossible - Fallout",           "year": 2018,
     "weights": {"genre": 1, "pace": -1, "darkness": 0},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["action_thriller"]},
    {"order": 38, "title": "Heat",                                    "year": 1995,
     "weights": {"genre": 1, "darkness": 1, "moral_ambiguity": 1, "emotional": 1, "pace": 1},
     "generation": ["classic", "millennial", "universal"],
     "scenes": ["action_thriller", "prestige_drama"]},
    {"order": 39, "title": "Die Hard",                                "year": 1988,
     "weights": {"genre": 1, "pace": -1, "irony": 1},
     "generation": ["classic", "universal"],
     "scenes": ["action_thriller"]},
    {"order": 40, "title": "Lethal Weapon",                           "year": 1987,
     "weights": {"genre": 1, "comedy": 1, "pace": -1, "emotional": 1},
     "generation": ["classic"],
     "scenes": ["action_thriller", "comedy"]},
    {"order": 41, "title": "Top Gun: Maverick",                       "year": 2022,
     "weights": {"genre": 1, "emotional": 1, "pace": -1, "darkness": -1},
     "generation": ["gen_z", "universal"],
     "scenes": ["action_thriller"]},
    {"order": 42, "title": "Casino Royale",                           "year": 2006,
     "weights": {"genre": 1, "darkness": 1, "moral_ambiguity": 1, "pace": 0},
     "generation": ["millennial", "universal"],
     "scenes": ["action_thriller"]},
    # Comedies (Phase D3b) — mainstream + buddy + smart comedy.
    # The existing pool had Annie Hall, Airplane!, Big Lebowski,
    # and Groundhog Day but needed buddy-comedy / romcom / gross-out
    # anchors the husband's scene actually cares about.
    {"order": 43, "title": "Hot Fuzz",                                "year": 2007,
     "weights": {"comedy": 2, "irony": 2, "genre": 1},
     "generation": ["millennial"],
     "scenes": ["comedy", "action_thriller"]},
    {"order": 44, "title": "21 Jump Street",                          "year": 2012,
     "weights": {"comedy": 2, "irony": 1, "genre": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["comedy", "action_thriller"]},
    {"order": 45, "title": "Superbad",                                "year": 2007,
     "weights": {"comedy": 2, "emotional": 1, "irony": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["comedy"]},
    {"order": 46, "title": "Tropic Thunder",                          "year": 2008,
     "weights": {"comedy": 2, "irony": 2, "genre": 1},
     "generation": ["millennial"],
     "scenes": ["comedy", "action_thriller"]},
    {"order": 47, "title": "Knives Out",                              "year": 2019,
     "weights": {"comedy": 1, "irony": 1, "genre": 1, "ambiguity": 1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["comedy", "action_thriller", "true_crime"]},
    {"order": 48, "title": "Bridesmaids",                             "year": 2011,
     "weights": {"comedy": 2, "emotional": 1, "irony": 1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["comedy", "romance"]},
]


# Profile definitions. Each profile has a signature vector that
# cosine-compares against the user's axis scores. Values are rough
# direction signals: 1.0 = high on this axis is defining, -1.0 =
# low is defining, 0 = not part of the profile.
PROFILES: list[dict] = [
    {
        "id": "patient_formalist",
        "name": "The Patient Formalist",
        "vector": {"pace": 1.0, "ambiguity": 1.0, "film_history": 1.0},
        "description": "You watch film as art. You're comfortable with slow, unresolved, visually driven work that asks you to sit with it.",
    },
    {
        "id": "genre_adventurer",
        "name": "The Genre Adventurer",
        "vector": {"genre": 1.0, "darkness": 1.0, "ambiguity": 1.0},
        "description": "You don't filter by genre. You're drawn to films that use horror, sci-fi, or thriller conventions to say something unexpected about the world.",
    },
    {
        "id": "emotional_realist",
        "name": "The Emotional Realist",
        "vector": {"emotional": 1.0, "irony": -1.0, "pace": 0.3},
        "description": "You need a story to feel true. You're drawn to performance, character, and emotional honesty — and suspicious of work that keeps its feelings at arm's length.",
    },
    {
        "id": "chaos_enjoyer",
        "name": "The Chaos Enjoyer",
        "vector": {"ambiguity": 1.0, "irony": 1.0, "darkness": 1.0},
        "description": "You find discomfort interesting. You're drawn to films that withhold resolution, subvert expectation, or leave you uncertain about what you just watched.",
    },
    {
        "id": "crowd_pleaser",
        "name": "The Crowd Pleaser",
        "vector": {"emotional": 1.0, "pace": -1.0, "irony": -1.0},
        "description": "You have a strong instinct for story and entertainment. You're not interested in being challenged for its own sake — and you're usually right about what's actually good.",
    },
    {
        "id": "dry_wit",
        "name": "The Dry Wit",
        "vector": {"irony": 1.0, "comedy": 1.0, "emotional": -1.0},
        "description": "Earnestness is suspicious. You're drawn to deadpan, absurdist, or formally self-aware comedy that doesn't take itself too seriously.",
    },
]


MIN_ANSWERED = 9


def score_responses(responses: list[dict]) -> dict:
    """Score quiz responses against the movie data. Thin wrapper that
    delegates the actual math to taste_quiz_scoring._score."""
    return _score(
        responses=responses,
        items=FILMS,
        axis_keys=AXIS_KEYS,
        profiles=PROFILES,
        min_answered=MIN_ANSWERED,
    )
