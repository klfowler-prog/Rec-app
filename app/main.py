from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware

from app.auth import _LoginRequired
from app.config import settings
from app.database import Base, engine
from app import models  # noqa: F401 — ensures all models are registered before create_all

Base.metadata.create_all(bind=engine)

# Auto-migrate: add new columns to existing tables if needed
with engine.connect() as conn:
    inspector = inspect(engine)
    if "media_entries" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("media_entries")]
        if "rated_at" not in columns:
            conn.execute(text("ALTER TABLE media_entries ADD COLUMN rated_at TIMESTAMP"))
            conn.commit()
    if "user_preferences" in inspector.get_table_names():
        up_columns = [c["name"] for c in inspector.get_columns("user_preferences")]
        if "quiz_results" not in up_columns:
            conn.execute(text("ALTER TABLE user_preferences ADD COLUMN quiz_results TEXT"))
            conn.commit()

    # One-time migration: convert 10-point ratings to 5-point scale.
    # Detects unconverted data by checking if any rating OR predicted_rating > 5.
    if "media_entries" in inspector.get_table_names():
        has_old_scale = conn.execute(
            text("SELECT 1 FROM media_entries WHERE rating > 5 OR predicted_rating > 5 LIMIT 1")
        ).fetchone()
        if has_old_scale:
            conn.execute(text(
                "UPDATE media_entries SET rating = GREATEST(1, ROUND(rating / 2.0)) WHERE rating IS NOT NULL AND rating > 5"
            ))
            conn.execute(text(
                "UPDATE media_entries SET predicted_rating = GREATEST(1.0, ROUND(predicted_rating::numeric / 2.0, 1)) WHERE predicted_rating IS NOT NULL AND predicted_rating > 5"
            ))
            conn.commit()
            # Flush all cached AI responses — they contain old 10-point data
            if "cache_entries" in inspector.get_table_names():
                conn.execute(text("DELETE FROM cache_entries"))
                conn.commit()

    # One-time fix: clear new_releases caches that were saved with the
    # wrong MIN_SCORE threshold (5.5 instead of 3.5). Safe to run once —
    # the cache will repopulate on next request.
    if "cache_entries" in inspector.get_table_names():
        conn.execute(text("DELETE FROM cache_entries WHERE key LIKE 'new_releases:%'"))
        conn.commit()

app = FastAPI(title="NextUp", description="Personal media recommendation engine")

# Session middleware for auth cookies
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=True, same_site="lax")


@app.exception_handler(_LoginRequired)
async def login_required_handler(request: Request, exc: _LoginRequired):
    is_api = (
        request.url.path.startswith("/api/")
        or "application/json" in request.headers.get("accept", "")
        or request.headers.get("authorization", "").startswith("Bearer ")
    )
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse("/welcome")


# Mount static files
static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

from app.routers import admin, auth, collections, device_auth, media, pages, profile, recommend, together

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(pages.router)
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
app.include_router(collections.router, prefix="/api/collections", tags=["collections"])
app.include_router(together.router, prefix="/api/together", tags=["together"])

# Device auth (pairing flow + token refresh)
app.include_router(device_auth.router, prefix="/api/v1/auth", tags=["device-auth"])

# v1 JSON API — stable namespace for TV/mobile clients (same routers, aliased prefix)
app.include_router(media.router, prefix="/api/v1/media", tags=["v1-media"])
app.include_router(profile.router, prefix="/api/v1/profile", tags=["v1-profile"])
app.include_router(together.router, prefix="/api/v1/together", tags=["v1-together"])
app.include_router(recommend.router, prefix="/api/v1/recommend", tags=["v1-recommend"])
