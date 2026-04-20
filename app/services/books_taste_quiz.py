"""Book taste quiz — two-module (fiction + nonfiction) static data.

Fiction module: 45 titles, 8 axes
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

RATING_MAP: dict[int, int] = {2: 5, 1: 4, 0: 3, -1: 1}


# FICTION MODULE — 45 titles in accessible → challenging order.
# note_in_ui is shown as a small caveat under the title when present.
# `generation` and `scenes` are Phase D2 pool tags used by the quiz
# load filter to match items against the user's saved onboarding.
FICTION: list[dict] = [
    {"order": 1,  "title": "Harry Potter and the Sorcerer's Stone", "author": "J.K. Rowling",
     "years": "1997–2007", "note_in_ui": "Rate the series as a whole, not just this book",
     "weights": {"emotional": 1, "commitment": 1, "darkness": -2, "prose": -1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["scifi_fantasy", "kids_family"]},
    {"order": 2,  "title": "The Kite Runner", "author": "Khaled Hosseini", "years": "2003",
     "weights": {"emotional": 2, "darkness": 1, "prose": -1, "ideas": -1},
     "generation": ["millennial"],
     "scenes": ["prestige_drama"]},
    {"order": 3,  "title": "To Kill a Mockingbird", "author": "Harper Lee", "years": "1960",
     "weights": {"emotional": 1, "irony": -1, "darkness": -1, "prose": 1},
     "generation": ["classic", "universal"],
     "scenes": ["prestige_drama"]},
    {"order": 4,  "title": "Gone Girl", "author": "Gillian Flynn", "years": "2012",
     "weights": {"plot": 2, "darkness": 1, "irony": 1, "prose": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["action_thriller", "true_crime"]},
    {"order": 5,  "title": "Pride and Prejudice", "author": "Jane Austen", "years": "1813",
     "weights": {"prose": 1, "irony": 1, "emotional": 1, "plot": -1},
     "generation": ["classic", "universal"],
     "scenes": ["romance", "prestige_drama"]},
    {"order": 6,  "title": "1984", "author": "George Orwell", "years": "1949",
     "weights": {"ideas": 2, "darkness": 1, "emotional": -1},
     "generation": ["classic", "universal"],
     "scenes": ["scifi_fantasy", "prestige_drama"]},
    {"order": 7,  "title": "Normal People", "author": "Sally Rooney", "years": "2018",
     "weights": {"emotional": 2, "prose": 1, "plot": -1},
     "generation": ["gen_z"],
     "scenes": ["romance", "prestige_drama", "indie_arthouse"]},
    {"order": 8,  "title": "The Great Gatsby", "author": "F. Scott Fitzgerald", "years": "1925",
     "weights": {"prose": 2, "irony": 1, "ideas": 1, "plot": -1},
     "generation": ["classic", "universal"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 9,  "title": "The Catcher in the Rye", "author": "J.D. Salinger", "years": "1951",
     "weights": {"irony": 2, "prose": 1, "emotional": 1, "plot": -1},
     "generation": ["classic", "universal"],
     "scenes": ["prestige_drama"]},
    {"order": 10, "title": "Pachinko", "author": "Min Jin Lee", "years": "2017",
     "weights": {"commitment": 2, "emotional": 2, "plot": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["prestige_drama", "k_content"]},
    {"order": 11, "title": "Slaughterhouse-Five", "author": "Kurt Vonnegut", "years": "1969",
     "weights": {"irony": 2, "ideas": 1, "darkness": 1, "plot": -1},
     "generation": ["classic"],
     "scenes": ["scifi_fantasy", "prestige_drama", "indie_arthouse"]},
    {"order": 12, "title": "A Little Life", "author": "Hanya Yanagihara", "years": "2015",
     "weights": {"darkness": 2, "emotional": 2, "commitment": 2, "prose": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 13, "title": "Catch-22", "author": "Joseph Heller", "years": "1961",
     "weights": {"irony": 2, "ideas": 1, "darkness": 1, "commitment": 1, "plot": -1},
     "generation": ["classic"],
     "scenes": ["comedy", "prestige_drama", "indie_arthouse"]},
    {"order": 14, "title": "Crime and Punishment", "author": "Fyodor Dostoevsky", "years": "1866",
     "weights": {"moral_ambiguity": 2, "ideas": 1, "darkness": 1, "commitment": 1, "prose": 1},
     "generation": ["classic"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 15, "title": "The Road", "author": "Cormac McCarthy", "years": "2006",
     "weights": {"darkness": 2, "prose": 2, "emotional": 1, "commitment": -1},
     "generation": ["millennial"],
     "scenes": ["prestige_drama", "scifi_fantasy", "indie_arthouse"]},
    {"order": 16, "title": "One Flew Over the Cuckoo's Nest", "author": "Ken Kesey", "years": "1962",
     "weights": {"moral_ambiguity": 2, "irony": 1, "darkness": 1, "prose": 1},
     "generation": ["classic"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 17, "title": "The Remains of the Day", "author": "Kazuo Ishiguro", "years": "1989",
     "weights": {"prose": 2, "irony": 1, "emotional": 1, "plot": -1},
     "generation": ["classic"],
     "scenes": ["prestige_drama", "romance", "indie_arthouse"]},
    {"order": 18, "title": "Beloved", "author": "Toni Morrison", "years": "1987",
     "weights": {"prose": 2, "darkness": 2, "emotional": 2, "irony": 1},
     "generation": ["classic"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 19, "title": "Infinite Jest", "author": "David Foster Wallace", "years": "1996",
     "weights": {"commitment": 2, "prose": 2, "ideas": 1, "irony": 1, "plot": -2},
     "generation": ["millennial"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    {"order": 20, "title": "Blood Meridian", "author": "Cormac McCarthy", "years": "1985",
     "weights": {"prose": 2, "darkness": 2, "irony": 1, "plot": -2},
     "generation": ["classic"],
     "scenes": ["prestige_drama", "indie_arthouse"]},
    # Additional mainstream/canonical fiction — sci-fi epic, YA,
    # modern bestsellers, contemporary literary. Gives readers more
    # surface to find titles they've actually read.
    {"order": 21, "title": "Dune", "author": "Frank Herbert", "years": "1965",
     "weights": {"commitment": 2, "ideas": 1, "prose": 1, "plot": 1},
     "generation": ["classic", "millennial", "gen_z", "universal"],
     "scenes": ["scifi_fantasy"]},
    {"order": 22, "title": "The Hunger Games", "author": "Suzanne Collins", "years": "2008",
     "weights": {"plot": 2, "emotional": 1, "darkness": 1, "prose": -1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["scifi_fantasy", "action_thriller", "kids_family"]},
    {"order": 23, "title": "The Seven Husbands of Evelyn Hugo", "author": "Taylor Jenkins Reid", "years": "2017",
     "weights": {"plot": 1, "emotional": 2, "prose": -1},
     "generation": ["gen_z"],
     "scenes": ["romance", "prestige_drama"]},
    {"order": 24, "title": "Where the Crawdads Sing", "author": "Delia Owens", "years": "2018",
     "weights": {"emotional": 2, "plot": 1, "prose": 1, "darkness": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["romance", "true_crime", "prestige_drama"]},
    {"order": 25, "title": "Tomorrow, and Tomorrow, and Tomorrow", "author": "Gabrielle Zevin", "years": "2022",
     "weights": {"emotional": 1, "ideas": 1, "prose": 1, "commitment": 1},
     "generation": ["gen_z"],
     "scenes": ["gaming_culture", "romance", "prestige_drama"]},
    # Mystery / thriller
    {"order": 26, "title": "The Girl on the Train", "author": "Paula Hawkins", "years": "2015",
     "weights": {"plot": 2, "darkness": 1, "irony": 1, "prose": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["suspense_mystery", "true_crime", "prestige_drama"]},
    {"order": 27, "title": "The Silent Patient", "author": "Alex Michaelides", "years": "2019",
     "weights": {"plot": 2, "darkness": 1, "moral_ambiguity": 1, "prose": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["suspense_mystery", "true_crime"]},
    {"order": 28, "title": "Big Little Lies", "author": "Liane Moriarty", "years": "2014",
     "weights": {"plot": 1, "irony": 1, "emotional": 1, "darkness": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["suspense_mystery", "comedy", "prestige_drama"]},
    {"order": 29, "title": "The Da Vinci Code", "author": "Dan Brown", "years": "2003",
     "weights": {"plot": 2, "prose": -2, "commitment": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["action_thriller", "suspense_mystery"]},
    # Romance / women's fiction
    {"order": 30, "title": "It Ends with Us", "author": "Colleen Hoover", "years": "2016",
     "weights": {"emotional": 2, "darkness": 1, "plot": 1, "prose": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["romance", "prestige_drama"]},
    {"order": 31, "title": "Beach Read", "author": "Emily Henry", "years": "2020",
     "weights": {"emotional": 1, "plot": 1, "irony": 1, "darkness": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["romance", "comedy", "feelgood_comfort"]},
    {"order": 32, "title": "The Notebook", "author": "Nicholas Sparks", "years": "1996",
     "weights": {"emotional": 2, "plot": 1, "prose": -1, "ideas": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["romance", "feelgood_comfort"]},
    {"order": 33, "title": "Outlander", "author": "Diana Gabaldon", "years": "1991",
     "weights": {"commitment": 2, "emotional": 1, "plot": 1},
     "generation": ["classic", "universal"],
     "scenes": ["romance", "scifi_fantasy", "history_war"]},
    # Historical fiction
    {"order": 34, "title": "All the Light We Cannot See", "author": "Anthony Doerr", "years": "2014",
     "weights": {"prose": 2, "emotional": 1, "darkness": 1},
     "generation": ["classic", "millennial"],
     "scenes": ["prestige_drama", "history_war"]},
    {"order": 35, "title": "The Book Thief", "author": "Markus Zusak", "years": "2005",
     "weights": {"emotional": 2, "irony": 1, "darkness": 1, "prose": 1},
     "generation": ["classic", "millennial"],
     "scenes": ["prestige_drama", "history_war", "kids_family"]},
    {"order": 36, "title": "The Pillars of the Earth", "author": "Ken Follett", "years": "1989",
     "weights": {"commitment": 2, "plot": 1, "darkness": 1, "prose": -1},
     "generation": ["classic", "universal"],
     "scenes": ["prestige_drama", "history_war"]},
    # Feel-good / comfort
    {"order": 37, "title": "A Man Called Ove", "author": "Fredrik Backman", "years": "2012",
     "weights": {"emotional": 2, "irony": 1, "darkness": -1, "prose": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["feelgood_comfort", "comedy"]},
    {"order": 38, "title": "The Midnight Library", "author": "Matt Haig", "years": "2020",
     "weights": {"emotional": 1, "ideas": 1, "darkness": -1, "plot": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["feelgood_comfort", "scifi_fantasy"]},
    {"order": 39, "title": "Eleanor Oliphant Is Completely Fine", "author": "Gail Honeyman", "years": "2017",
     "weights": {"emotional": 2, "irony": 1, "darkness": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["feelgood_comfort", "prestige_drama"]},
    # YA
    {"order": 40, "title": "The Fault in Our Stars", "author": "John Green", "years": "2012",
     "weights": {"emotional": 2, "irony": 1, "darkness": 1, "prose": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["romance", "kids_family", "prestige_drama"]},
    {"order": 41, "title": "Percy Jackson and the Lightning Thief", "author": "Rick Riordan", "years": "2005",
     "weights": {"plot": 2, "emotional": 1, "darkness": -1, "prose": -1},
     "generation": ["classic", "millennial", "gen_z", "universal"],
     "scenes": ["scifi_fantasy", "kids_family", "action_thriller"]},
    {"order": 42, "title": "Divergent", "author": "Veronica Roth", "years": "2011",
     "weights": {"plot": 2, "darkness": 1, "emotional": 1, "prose": -1},
     "generation": ["classic", "millennial"],
     "scenes": ["scifi_fantasy", "action_thriller", "kids_family"]},
    # Horror
    {"order": 43, "title": "The Shining", "author": "Stephen King", "years": "1977",
     "weights": {"darkness": 2, "plot": 1, "emotional": 1, "moral_ambiguity": 1},
     "generation": ["classic", "universal"],
     "scenes": ["horror", "prestige_drama"]},
    {"order": 44, "title": "Mexican Gothic", "author": "Silvia Moreno-Garcia", "years": "2020",
     "weights": {"darkness": 2, "prose": 1, "irony": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["horror", "history_war", "indie_arthouse"]},
    # Faith / inspirational
    {"order": 45, "title": "Where the Red Fern Grows", "author": "Wilson Rawls", "years": "1961",
     "weights": {"emotional": 2, "darkness": -1, "prose": -1, "irony": -1},
     "generation": ["classic", "millennial", "gen_z", "universal"],
     "scenes": ["faith_family", "kids_family", "feelgood_comfort"]},
]


# NONFICTION MODULE — 15 titles in presentation order.
# These carry the extra nonfiction_register axis: positive = ideas-
# first argument-driven (Sapiens, How to Change Your Mind), negative
# = narrative-first story-driven (Educated, The Years). The
# docs_nonfiction scene is the default landing place for a nonfiction
# reader's taste; additional scene tags (true_crime, music, etc.)
# layer on top when the book specifically lives in that world.
NONFICTION: list[dict] = [
    {"order": 1,  "title": "Educated", "author": "Tara Westover", "years": "2018",
     "weights": {"emotional": 2, "darkness": 1, "plot": 1, "prose": -1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["docs_nonfiction", "prestige_drama"]},
    {"order": 2,  "title": "The Immortal Life of Henrietta Lacks", "author": "Rebecca Skloot", "years": "2010",
     "weights": {"emotional": 2, "moral_ambiguity": 1, "nonfiction_register": 1, "plot": 1},
     "generation": ["millennial"],
     "scenes": ["docs_nonfiction", "true_crime"]},
    {"order": 3,  "title": "When Breath Becomes Air", "author": "Paul Kalanithi", "years": "2016",
     "weights": {"emotional": 2, "darkness": 2, "prose": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["docs_nonfiction"]},
    {"order": 4,  "title": "Sapiens", "author": "Yuval Noah Harari", "years": "2011",
     "weights": {"ideas": 2, "nonfiction_register": 2, "emotional": -1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 5,  "title": "Into the Wild", "author": "Jon Krakauer", "years": "1996",
     "weights": {"moral_ambiguity": 2, "plot": 1, "emotional": 1},
     "generation": ["millennial"],
     "scenes": ["docs_nonfiction", "true_crime"]},
    {"order": 6,  "title": "The Body Keeps the Score", "author": "Bessel van der Kolk", "years": "2014",
     "weights": {"emotional": 1, "ideas": 1, "nonfiction_register": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 7,  "title": "Say Nothing", "author": "Patrick Radden Keefe", "years": "2018",
     "weights": {"darkness": 2, "moral_ambiguity": 2, "plot": 1, "nonfiction_register": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["true_crime", "docs_nonfiction"]},
    {"order": 8,  "title": "In Cold Blood", "author": "Truman Capote", "years": "1966",
     "weights": {"prose": 2, "darkness": 2, "moral_ambiguity": 1, "nonfiction_register": 1},
     "generation": ["classic"],
     "scenes": ["true_crime", "docs_nonfiction"]},
    {"order": 9,  "title": "Untamed", "author": "Glennon Doyle", "years": "2020",
     "weights": {"emotional": 2, "ideas": 1, "nonfiction_register": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 10, "title": "How to Change Your Mind", "author": "Michael Pollan", "years": "2018",
     "weights": {"ideas": 2, "nonfiction_register": 1, "prose": 1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["docs_nonfiction"]},
    # Additional nonfiction — two more ideas books, two more narrative
    # memoirs, one investigative. Broadens the surface to match the
    # fiction module's new size.
    {"order": 11, "title": "Atomic Habits", "author": "James Clear", "years": "2018",
     "weights": {"ideas": 2, "nonfiction_register": 2, "emotional": -1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["docs_nonfiction"]},
    {"order": 12, "title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "years": "2011",
     "weights": {"ideas": 2, "nonfiction_register": 2, "commitment": 1, "emotional": -1},
     "generation": ["millennial"],
     "scenes": ["docs_nonfiction"]},
    {"order": 13, "title": "Just Mercy", "author": "Bryan Stevenson", "years": "2014",
     "weights": {"emotional": 2, "darkness": 1, "moral_ambiguity": 1, "nonfiction_register": -1},
     "generation": ["millennial"],
     "scenes": ["docs_nonfiction", "true_crime"]},
    {"order": 14, "title": "The Glass Castle", "author": "Jeannette Walls", "years": "2005",
     "weights": {"emotional": 2, "darkness": 1, "plot": 1, "prose": 1},
     "generation": ["millennial"],
     "scenes": ["docs_nonfiction"]},
    {"order": 15, "title": "Bad Blood", "author": "John Carreyrou", "years": "2018",
     "weights": {"plot": 2, "moral_ambiguity": 1, "darkness": 1, "nonfiction_register": -1},
     "generation": ["gen_z", "millennial"],
     "scenes": ["docs_nonfiction", "true_crime"]},
    # Science, space, geopolitics, economics, military — broader appeal
    {"order": 16, "title": "A Short History of Nearly Everything", "author": "Bill Bryson", "years": "2003",
     "weights": {"ideas": 2, "nonfiction_register": 1, "prose": 1, "emotional": -1},
     "generation": ["millennial", "gen_x", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 17, "title": "Daring Greatly", "author": "Brené Brown", "years": "2012",
     "weights": {"emotional": 2, "ideas": 1, "nonfiction_register": 1},
     "generation": ["millennial", "gen_x", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 18, "title": "Freakonomics", "author": "Steven D. Levitt", "years": "2005",
     "weights": {"ideas": 2, "irony": 1, "nonfiction_register": 1, "emotional": -1},
     "generation": ["millennial", "gen_x"],
     "scenes": ["docs_nonfiction"]},
    {"order": 19, "title": "The Subtle Art of Not Giving a F*ck", "author": "Mark Manson", "years": "2016",
     "weights": {"ideas": 1, "irony": 2, "nonfiction_register": 1, "emotional": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 20, "title": "Endurance", "author": "Alfred Lansing", "years": "1959",
     "weights": {"plot": 2, "emotional": 1, "darkness": 1, "nonfiction_register": -1},
     "generation": ["gen_x", "boomer", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 21, "title": "The 5 Second Rule", "author": "Mel Robbins", "years": "2017",
     "weights": {"ideas": 1, "emotional": 1, "nonfiction_register": 2},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 22, "title": "Outliers", "author": "Malcolm Gladwell", "years": "2008",
     "weights": {"ideas": 2, "nonfiction_register": 1, "emotional": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 23, "title": "You Are a Badass", "author": "Jen Sincero", "years": "2013",
     "weights": {"emotional": 1, "ideas": 1, "nonfiction_register": 2, "irony": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 24, "title": "Astrophysics for People in a Hurry", "author": "Neil deGrasse Tyson", "years": "2017",
     "weights": {"ideas": 2, "nonfiction_register": 1, "commitment": -1, "emotional": -1},
     "generation": ["gen_z", "millennial", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 25, "title": "Greenlights", "author": "Matthew McConaughey", "years": "2020",
     "weights": {"emotional": 1, "plot": 1, "irony": 1, "nonfiction_register": -1},
     "generation": ["millennial", "gen_x"],
     "scenes": ["docs_nonfiction"]},
    {"order": 26, "title": "Shoe Dog", "author": "Phil Knight", "years": "2016",
     "weights": {"plot": 2, "emotional": 1, "nonfiction_register": -1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 27, "title": "Born a Crime", "author": "Trevor Noah", "years": "2016",
     "weights": {"emotional": 2, "plot": 1, "irony": 1, "darkness": 1},
     "generation": ["millennial", "gen_z", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 28, "title": "Unbroken", "author": "Laura Hillenbrand", "years": "2010",
     "weights": {"plot": 2, "emotional": 2, "darkness": 1, "nonfiction_register": -1},
     "generation": ["millennial", "gen_x", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 29, "title": "Becoming", "author": "Michelle Obama", "years": "2018",
     "weights": {"emotional": 2, "plot": 1, "nonfiction_register": -1},
     "generation": ["millennial", "gen_x", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 30, "title": "Can't Hurt Me", "author": "David Goggins", "years": "2018",
     "weights": {"emotional": 2, "darkness": 1, "nonfiction_register": 1, "plot": 1},
     "generation": ["millennial", "gen_z"],
     "scenes": ["docs_nonfiction"]},
    {"order": 31, "title": "The Four Agreements", "author": "Don Miguel Ruiz", "years": "1997",
     "weights": {"ideas": 1, "emotional": 1, "nonfiction_register": 2, "commitment": -1},
     "generation": ["millennial", "gen_x", "universal"],
     "scenes": ["docs_nonfiction"]},
    {"order": 32, "title": "Girl, Wash Your Face", "author": "Rachel Hollis", "years": "2018",
     "weights": {"emotional": 2, "nonfiction_register": 2, "ideas": 1},
     "generation": ["millennial"],
     "scenes": ["docs_nonfiction"]},
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
    # Scene-driven profile signatures (Phase E3). Previously the
    # books profile list leaned prestige-literary — a reader of
    # Normal People + Seven Husbands + The Hunger Games got back
    # descriptions that didn't describe them. These three fill in
    # the romance, genre escape, and true-crime slices that the
    # plan's 'edge-case media diets' section identified.
    {
        "id": "romance_reader",
        "name": "The Romance Reader",
        "vector": {"emotional": 1.0, "plot": 1.0, "darkness": -0.5, "irony": -0.3},
        "description": "Love stories are the point, whether they're contemporary romcoms, period drama, or literary romance. You want books that take feeling seriously — earned emotional beats, relationships that matter, and an ending that pays off the buildup.",
    },
    {
        "id": "genre_escapist",
        "name": "The Genre Escapist",
        "vector": {"plot": 1.0, "commitment": 0.5, "prose": -0.3, "ideas": 0.3},
        "description": "Dune, Harry Potter, Hunger Games, Gone Girl — you read to be pulled into a world bigger than yours and stay until you've finished the series. Plot is the contract; stakes and pacing are what keep you turning pages.",
    },
    {
        "id": "true_crime_reader",
        "name": "The True Crime Reader",
        "vector": {"plot": 1.0, "darkness": 1.0, "moral_ambiguity": 1.0, "nonfiction_register": -0.3},
        "description": "Say Nothing, In Cold Blood, Bad Blood, Just Mercy — you want true stories with the pacing and moral weight of a great thriller, and you're comfortable sitting with how dark reality actually is.",
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
    # When fiction-only, exclude profiles that depend on nonfiction_register
    _nonfiction_profiles = {"narrative_nonfiction", "ideas_first_nonfiction"}
    eligible_profiles = PROFILES
    if use_fiction and not use_nonfiction:
        eligible_profiles = [p for p in PROFILES if p["id"] not in _nonfiction_profiles]

    user_vec = [combined[k] for k in AXIS_KEYS]
    norm_u = math.sqrt(sum(v * v for v in user_vec))
    ranked: list[dict] = []
    for profile in eligible_profiles:
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
