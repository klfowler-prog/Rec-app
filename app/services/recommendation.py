import json
from collections.abc import AsyncGenerator

from sqlalchemy.orm import Session

from app.config import settings
from app.models import MediaEntry, UserPreferences


def _build_profile_context(db: Session) -> str:
    """Build a structured summary of the user's taste profile for the AI."""
    entries = db.query(MediaEntry).all()
    prefs = db.query(UserPreferences).filter(UserPreferences.id == "default").first()

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


SYSTEM_PROMPT = """You are a personal media recommendation assistant called NextUp. You have deep knowledge of the user's taste profile (provided below) and are an expert in movies, TV shows, books, and podcasts.

{profile_context}

## Your Guidelines:
- Recommend 3-5 items per request unless the user asks for more or fewer
- Explain WHY each recommendation fits the user's taste — reference specific items from their profile
- Include the media type, year, and creator (director/author/host) for each recommendation
- Be conversational and friendly, not robotic
- If the user's request is vague, ask a clarifying question before recommending
- You can recommend across media types unless the user specifies one
- If the user says they've already seen/read something, acknowledge it and suggest alternatives
- Don't recommend items that are already in the user's profile unless they ask for rewatches/rereads

Format each recommendation clearly with the title in bold, followed by the type, year, and a brief explanation of why it's a good fit."""


async def stream_recommendation(
    message: str,
    media_type: str | None,
    history: list[dict],
    db: Session,
) -> AsyncGenerator[str, None]:
    """Stream a recommendation response from Gemini."""
    profile_context = _build_profile_context(db)
    system_prompt = SYSTEM_PROMPT.format(profile_context=profile_context)

    if media_type:
        message = f"[Looking specifically for {media_type}s] {message}"

    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=system_prompt,
    )

    # Build conversation history
    chat_history = []
    for msg in history:
        role = "user" if msg.get("role") == "user" else "model"
        chat_history.append({"role": role, "parts": [msg.get("content", "")]})

    chat = model.start_chat(history=chat_history)

    try:
        response = chat.send_message(message, stream=True)
        full_response = ""
        for chunk in response:
            if chunk.text:
                full_response += chunk.text
                yield f"data: {json.dumps({'text': chunk.text})}\n\n"

        # Save to recommendation history
        from app.models import Recommendation
        rec = Recommendation(query=message, response=full_response, media_type_filter=media_type)
        db.add(rec)
        db.commit()

        yield f"data: {json.dumps({'done': True})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
