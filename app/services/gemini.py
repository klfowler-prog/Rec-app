"""Gemini API client using REST directly — no SDK needed."""

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-2.0-flash-001"


async def generate(prompt: str, system_instruction: str = "") -> str:
    """Generate content from Gemini. Returns the text response."""
    if not settings.gemini_api_key:
        log.error("GEMINI_API_KEY is not set")
        return ""

    url = f"{BASE_URL}/models/{MODEL}:generateContent"
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
        if resp.status_code != 200:
            log.error("Gemini API error %s: %s", resp.status_code, resp.text[:500])
            return ""
        data = resp.json()

    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")
    log.warning("Gemini returned no candidates: %s", str(data)[:300])
    return ""


async def generate_stream(prompt: str, system_instruction: str = "", history: list[dict] | None = None):
    """Stream content from Gemini. Yields text chunks."""
    if not settings.gemini_api_key:
        log.error("GEMINI_API_KEY is not set")
        return

    url = f"{BASE_URL}/models/{MODEL}:streamGenerateContent"

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
            if resp.status_code != 200:
                error_body = await resp.aread()
                log.error("Gemini stream error %s: %s", resp.status_code, error_body[:500])
                return
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
