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
    high_rated = [e for e in entries if e.rating and e.rating >= 8]
    high_rated.sort(key=lambda e: e.rating or 0, reverse=True)

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
        lines.append("### Highly Rated (8+/10):")
        for e in high_rated[:15]:
            genre_str = f" [{e.genres}]" if e.genres else ""
            lines.append(f"- {e.title} ({e.media_type}, {e.year or 'unknown year'}) — rated {e.rating}/10{genre_str}")
        lines.append("")

    lines.append("### Recently Added:")
    for e in recent:
        rating_str = f" rated {e.rating}/10" if e.rating else ""
        lines.append(f"- {e.title} ({e.media_type}) — {e.status}{rating_str}")
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

    return "\n".join(lines)


SYSTEM_PROMPT = """You are a personal media recommendation assistant called NextUp. You have deep knowledge of the user's taste profile (provided below) and are an expert in cross-medium connections — finding links between books, TV, movies, and podcasts (fiction AND nonfiction) that share themes, ideas, tone, or emotional register.

{profile_context}

## Your Guidelines:
- Recommend 3-5 items per request unless the user asks for more or fewer
- Nonfiction is welcome: documentaries, memoirs, idea books, narrative nonfiction, interview/science/news/explainer podcasts. Match the user's fiction/nonfiction balance — if they rate nonfiction highly, recommend more.
- Explain WHY each recommendation fits the user's taste. Reference specific items from their profile, ideally from a DIFFERENT media type (cross-medium connection).
- The connection must be CONCRETE — cite a shared theme, idea, emotional beat, or narrative approach. Never rely on shared demographic, setting, or keyword alone.
- Be conversational and friendly, not robotic
- If the user's request is vague, ask a clarifying question before recommending
- You can recommend across media types unless the user specifies one
- If the user says they've already seen/read something, acknowledge it and suggest alternatives

## Response Format:

Write a conversational prose response (1-3 paragraphs max) with recommendations explained in a friendly way.

Then, at the very end of your response, include a special JSON block for structured parsing:

===ITEMS===
[
  {"title": "...", "media_type": "movie|tv|book|podcast", "year": 2020, "reason": "one-sentence cross-medium reason citing a concrete element"},
  {"title": "...", "media_type": "...", "year": 2020, "reason": "..."}
]
===END===

The ===ITEMS=== block is REQUIRED. Include every item you recommended in prose as a JSON entry. This is how the app renders action cards after your text."""


async def stream_recommendation(
    message: str,
    media_type: str | None,
    history: list[dict],
    db: Session,
    user_id: int = 0,
) -> AsyncGenerator[str, None]:
    """Stream a recommendation response from Gemini."""
    profile_context = _build_profile_context(db, user_id)
    system_prompt = SYSTEM_PROMPT.format(profile_context=profile_context)

    if media_type:
        message = f"[Looking specifically for {media_type}s] {message}"

    if not settings.gemini_api_key:
        yield f'data: {{"error": "Gemini API key not configured. Add GEMINI_API_KEY to your .env file."}}\n\n'
        return

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
