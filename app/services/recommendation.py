import json
from collections.abc import AsyncGenerator

from sqlalchemy.orm import Session

from app.config import settings
from app.models import MediaEntry, UserPreferences


def _build_profile_context(db: Session, user_id: int) -> str:
    """Build a structured summary of the user's taste profile for the AI."""
    entries = db.query(MediaEntry).filter(MediaEntry.user_id == user_id).all()
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()

    if not entries:
        return "The user's profile is empty — they haven't added any media yet. Ask them about their general preferences to give recommendations."

    # High-rated items
    high_rated = [e for e in entries if e.rating and e.rating >= 4]
    high_rated.sort(key=lambda e: e.rating or 0, reverse=True)

    # Abandoned items — strong negative signal about what didn't work
    abandoned = [e for e in entries if e.status == "abandoned"]

    # Recently consumed
    recent = sorted(entries, key=lambda e: e.created_at, reverse=True)[:10]

    # Genre frequency
    genre_counts: dict[str, int] = {}
    for e in entries:
        if e.genres:
            for g in e.genres.split(","):
                g = g.strip()
                if g:
                    genre_counts[g] = genre_counts.get(g, 0) + 1
    top_genres = sorted(genre_counts, key=genre_counts.get, reverse=True)[:8]

    # Build context
    lines = ["## User's Taste Profile", ""]

    if high_rated:
        lines.append("### Highly Rated (4+/5):")
        for e in high_rated[:15]:
            genre_str = f" [{e.genres}]" if e.genres else ""
            lines.append(f"- {e.title} ({e.media_type}, {e.year or 'unknown year'}) — rated {e.rating}/5{genre_str}")
        lines.append("")

    lines.append("### Recently Added:")
    for e in recent:
        rating_str = f" rated {e.rating}/5" if e.rating else ""
        lines.append(f"- {e.title} ({e.media_type}) — {e.status}{rating_str}")
    lines.append("")

    if abandoned:
        lines.append("### Abandoned / Didn't Finish:")
        lines.append("These are items the user started but dropped. Treat as soft negative signal — something about the tone, pacing, subject, or style didn't work for them. Avoid recommending items with similar characteristics.")
        for e in abandoned[:10]:
            genre_str = f" [{e.genres}]" if e.genres else ""
            lines.append(f"- {e.title} ({e.media_type}){genre_str}")
        lines.append("")

    if top_genres:
        lines.append(f"### Genre Preferences:")
        lines.append(f"Most enjoyed: {', '.join(top_genres)}")

    if prefs and prefs.disliked_genres:
        try:
            disliked = json.loads(prefs.disliked_genres)
            lines.append(f"Tends to avoid: {', '.join(disliked)}")
        except json.JSONDecodeError:
            pass

    lines.append("")
    lines.append(f"### Profile Summary:")
    lines.append(f"Total items: {len(entries)}")
    type_counts = {}
    for e in entries:
        type_counts[e.media_type] = type_counts.get(e.media_type, 0) + 1
    lines.append(f"Breakdown: {', '.join(f'{v} {k}s' for k, v in type_counts.items())}")

    # Explicit do-not-recommend list — cap at ~6000 chars so the AI
    # always has enough context to avoid suggesting something already owned.
    avoid_titles: list[str] = []
    char_budget = 6000
    for e in entries:
        if char_budget <= 0:
            break
        avoid_titles.append(e.title)
        char_budget -= len(e.title) + 2
    if avoid_titles:
        lines.append("")
        lines.append("### DO NOT RECOMMEND — already in their library:")
        lines.append(", ".join(avoid_titles))

    # Age range — adjusts content appropriateness and era awareness
    from app.services.taste_quiz_scoring import load_age_range
    age = load_age_range(db, user_id)
    if age == "under_18":
        lines.append("\n### Age: Under 18\nOnly recommend PG/PG-13 content. No R-rated, no explicit themes. Focus on 2010-present across all media types.")
    elif age == "35_50":
        lines.append("\n### Age: 35-50\nInclude titles from the 90s-2020s. Respect their depth across movies, TV, books, and podcasts.")
    elif age == "over_50":
        lines.append("\n### Age: Over 50\nInclude classics from the 70s-2000s alongside newer content. Don't assume they only engage with old media — but respect their experience.")

    # Streaming services
    from app.services.taste_quiz_scoring import load_streaming_services
    from app.services.tmdb import TIER1_PROVIDERS
    user_services = load_streaming_services(db, user_id)
    if user_services:
        service_names = [TIER1_PROVIDERS.get(pid, f"Service {pid}") for pid in user_services]
        lines.append("")
        lines.append(f"### Streaming Services: {', '.join(service_names)}")
        lines.append("Strongly prefer movies and TV available on these services. If recommending something not on their services, mention where it's available and that it can be rented/bought.")

    return "\n".join(lines)


SYSTEM_PROMPT = """You are a personal media recommendation assistant called NextUp. You have deep knowledge of the user's taste profile (provided below) and you're great at finding connections between books, TV, movies, and podcasts (fiction AND nonfiction) that share themes, ideas, tone, or feel.

{profile_context}

## Your Guidelines:
- Recommend 3-5 items per request unless the user asks for more or fewer
- CRITICAL: NEVER recommend anything from the "DO NOT RECOMMEND" list in the profile above. That list is the user's existing library — recommending from it is a failure. If the user asks for something you'd normally suggest from that list, pick an adjacent item instead and note that they already have the obvious pick.
- RECENCY BALANCE: The "Recently Added" items are ONE signal, not the whole picture. Don't over-index on the last thing rated. Use the FULL taste profile — the breadth of highly-rated items across genres, types, and years — as the primary driver. Recent activity is a tiebreaker, not a pivot.
- If the user is trying to REMEMBER or IDENTIFY a specific title ("what was that podcast about…", "the book I was reading last year…", "the show with the guy who…"), treat it as a lookup, not a recommendation request. If there's a "REAL CANDIDATES FROM SEARCH" block above, prefer titles from that list — those are grounded in the real podcast/book/movie APIs. Name the most likely match, briefly explain why you think so, and offer one or two alternatives if uncertain. Do NOT invent a title.
- Nonfiction is welcome: documentaries, memoirs, idea books, narrative nonfiction, interview/science/news/explainer podcasts. Match the user's fiction/nonfiction balance — if they rate nonfiction highly, recommend more.
- Explain WHY each recommendation fits the user's taste. Reference specific items from their profile, ideally from a DIFFERENT media type (cross-medium connection).
- The connection must be CONCRETE — explain what they have in common — the ideas, the feelings, the way they tell their story. Don't just match on surface stuff.
- Some items in a user's library are purely PRACTICAL (e.g. a book about adopting a dog, a home repair guide, a cookbook). Don't over-index on these when building taste connections — they reflect a life need, not a taste signal. Focus your taste model on items that reflect how the user engages with story, ideas, and entertainment.
- GENRE DEPTH vs EXPOSURE: One or two items in a genre does NOT make someone a fan. Someone who watched Spirited Away doesn't want niche anime. Someone who read one thriller doesn't want serial-killer deep cuts. Look at density — how many items in the genre, how highly rated. A single item means casual exposure; five highly-rated items means genuine enthusiasm. Only go deep into a genre when the profile shows real depth there.
- Be conversational and friendly, not robotic
- If the user's request is vague, ask a clarifying question before recommending
- You can recommend across media types unless the user specifies one

## BLEND REQUESTS ("feels like X meets Y"):
When the user asks for something that "feels like X meets Y" or similar blend language:
1. FIRST, analyze what makes each reference title distinctive — not just genre, but the specific qualities: tone, pacing, mood, storytelling style, themes, the *feeling* of engaging with it. Be specific: "The Matrix" isn't just "sci-fi action" — it's philosophical paranoia wrapped in stylish action with a chosen-one arc. "Harry Potter" isn't just "fantasy" — it's found-family warmth in a whimsical world with escalating darkness.
2. THEN, identify the intersection — what would something that captures BOTH qualities actually feel like? What's the Venn diagram overlap?
3. ONLY THEN pick items that genuinely live in that intersection. The blend should be the PRIMARY driver of your picks, not the user's general taste profile. The profile is a secondary filter (don't recommend something they'd hate based on their profile, but the blend dictates the direction).
4. In your response, lead with the blend analysis: "The Matrix meets Harry Potter — you're looking for [specific intersection]. Here's what lives there."
5. Each recommendation's reason should reference BOTH source titles, not just one.

## LIBRARY AWARENESS:
If the user mentions or asks about a title that's in their "DO NOT RECOMMEND" list, acknowledge it naturally: "You've already seen X — great pick. Based on what you loved about it..." or "I see you have X in your library." Don't just silently skip it. If ALL your top picks would be things they've already consumed, say so and explain why, then suggest adjacent items they haven't tried.

## Response Format:

Write a well-formatted response using markdown:
- Use **bold** for title names
- Use paragraph breaks between distinct ideas
- When listing multiple recommendations, use a brief intro paragraph, then a separate paragraph per recommendation with the title bolded at the start
- Keep each recommendation paragraph to 2-3 sentences max — punchy, not rambling
- Use line breaks generously — dense walls of text are hard to read

Then, at the very end of your response, include a special JSON block for structured parsing:

===ITEMS===
[
  {"title": "...", "creator": "author/director name", "media_type": "movie|tv|book|podcast", "year": 2020, "reason": "What it is (1 sentence premise) + why you'll like it (connection to profile)"},
  {"title": "...", "creator": "...", "media_type": "...", "year": 2020, "reason": "..."}
]
===END===

The ===ITEMS=== block is REQUIRED. Include every item you recommended in prose as a JSON entry. The "creator" field is REQUIRED — include the author, director, or creator name for accurate search matching. This is how the app renders action cards after your text."""


async def stream_recommendation(
    message: str,
    media_type: str | None,
    history: list[dict],
    db: Session,
    user_id: int = 0,
) -> AsyncGenerator[str, None]:
    """Stream a recommendation response from Gemini."""
    profile_context = _build_profile_context(db, user_id)
    # Use .replace(), NOT .format() — SYSTEM_PROMPT contains literal
    # `{"title": ...}` inside the JSON example block, which str.format()
    # would try to parse as format placeholders and raise KeyError.
    system_prompt = SYSTEM_PROMPT.replace("{profile_context}", profile_context)

    # Inject taste-quiz signals into the system prompt so the chat
    # can cross-reference the user's quiz direction (e.g. "Patient
    # Formalist in film") when making recommendations in another
    # medium. Returns empty string if no quizzes completed.
    try:
        from app.services.taste_quiz_scoring import build_quiz_signals_block
        quiz_signals = build_quiz_signals_block(db, user_id)
        if quiz_signals:
            system_prompt = quiz_signals + "\n" + system_prompt
    except Exception:
        pass

    if not settings.gemini_api_key:
        yield f'data: {{"error": "Gemini API key not configured. Add GEMINI_API_KEY to your .env file."}}\n\n'
        return

    # Ground the chat in real API data. Gemini on its own can't look up
    # things outside its training, so if the user is asking "what was
    # that podcast about X" or "recommend a book on Y", we run the
    # query through our search APIs first and inject real candidates
    # into the system prompt. The AI then has actual titles it can
    # reference instead of guessing.
    search_context = ""
    try:
        from app.services.unified_search import unified_search

        # Build a search query from the user's message. Strip any
        # obvious conversational filler so the search APIs get clean
        # keywords.
        search_query = message.strip()
        # Cap length so we don't send a 500-char essay to the APIs.
        if len(search_query) > 200:
            search_query = search_query[:200]

        hits = await unified_search(search_query, media_type)
        if hits:
            lines = ["REAL CANDIDATES FROM SEARCH (use these exact titles if any match what the user is asking about — do not invent titles when one of these fits):"]
            # Keep it tight — top 12 across types, prefer ones with
            # creator info so the AI can cite authors/hosts.
            for h in hits[:12]:
                year_str = f" ({h.year})" if h.year else ""
                creator_str = f" — {h.creator}" if h.creator else ""
                lines.append(f"- [{h.media_type}] {h.title}{year_str}{creator_str}")
            search_context = "\n".join(lines) + "\n\n"
    except Exception:
        # Search is best-effort. If the APIs fail, fall back to
        # Gemini's training knowledge.
        pass

    if media_type:
        message = f"[Looking specifically for {media_type}s] {message}"

    # Prepend the search context to the system prompt so the model
    # sees real titles before generating its answer.
    if search_context:
        system_prompt = search_context + system_prompt

    from app.services.gemini import generate_stream

    try:
        full_response = ""
        async for chunk in generate_stream(message, system_instruction=system_prompt, history=history):
            full_response += chunk
            yield f"data: {json.dumps({'text': chunk})}\n\n"

        # Save to recommendation history
        from app.models import Recommendation
        rec = Recommendation(user_id=user_id, query=message, response=full_response, media_type_filter=media_type)
        db.add(rec)
        db.commit()

        yield f"data: {json.dumps({'done': True})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
