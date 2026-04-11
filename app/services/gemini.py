"""Gemini API client using REST directly — no SDK needed."""

import httpx

from app.config import settings

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


async def generate(prompt: str, system_instruction: str = "") -> str:
    """Generate content from Gemini. Returns the text response."""
    url = f"{BASE_URL}/models/gemini-2.0-flash:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
    }
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")
    return ""


async def generate_stream(prompt: str, system_instruction: str = "", history: list[dict] | None = None):
    """Stream content from Gemini. Yields text chunks."""
    url = f"{BASE_URL}/models/gemini-2.0-flash:streamGenerateContent"

    contents = []
    if history:
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    body = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            url,
            params={"key": settings.gemini_api_key, "alt": "sse"},
            json=body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    import json
                    try:
                        chunk = json.loads(line[6:])
                        candidates = chunk.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                text = parts[0].get("text", "")
                                if text:
                                    yield text
                    except json.JSONDecodeError:
                        pass
