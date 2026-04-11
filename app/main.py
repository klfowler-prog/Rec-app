from sqlalchemy import inspect, text
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import media, pages, profile, recommend

Base.metadata.create_all(bind=engine)

# Add new columns to existing tables if they don't exist yet
with engine.connect() as conn:
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns("media_entries")]
    if "predicted_rating" not in columns:
        conn.execute(text("ALTER TABLE media_entries ADD COLUMN predicted_rating REAL"))
        conn.commit()

app = FastAPI(title="NextUp", description="Personal media recommendation engine")

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(pages.router)
app.include_router(media.router, prefix="/api/media", tags=["media"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(recommend.router, prefix="/api/recommend", tags=["recommend"])
