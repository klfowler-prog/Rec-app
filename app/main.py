from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import media, pages, profile, recommend

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Rec", description="Personal media recommendation engine")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(pages.router)
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
