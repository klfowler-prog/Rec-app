from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware

from app.auth import _LoginRequired
from app.config import settings
from app.database import Base, engine
from app.routers import auth, media, pages, profile, recommend

Base.metadata.create_all(bind=engine)

# Auto-migrate: add new columns to existing tables if needed
with engine.connect() as conn:
    inspector = inspect(engine)
    if "media_entries" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("media_entries")]
        if "predicted_rating" not in columns:
            conn.execute(text("ALTER TABLE media_entries ADD COLUMN predicted_rating REAL"))
            conn.commit()
        if "user_id" not in columns:
            conn.execute(text("ALTER TABLE media_entries ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()
    if "recommendations" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("recommendations")]
        if "user_id" not in columns:
            conn.execute(text("ALTER TABLE recommendations ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            conn.commit()

app = FastAPI(title="NextUp", description="Personal media recommendation engine")

# Session middleware for auth cookies
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.exception_handler(_LoginRequired)
async def login_required_handler(request: Request, exc: _LoginRequired):
    return RedirectResponse("/auth/login")


app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(pages.router)
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
