from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import _LoginRequired
from app.config import settings
from app.database import Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="NextUp", description="Personal media recommendation engine")

# Session middleware for auth cookies
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.exception_handler(_LoginRequired)
async def login_required_handler(request: Request, exc: _LoginRequired):
    return RedirectResponse("/auth/login")


# Mount static files
static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

from app.routers import auth, media, pages, profile, recommend

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(pages.router)
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
