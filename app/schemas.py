from datetime import datetime

from pydantic import BaseModel


class MediaResult(BaseModel):
    external_id: str
    source: str
    media_type: str
    title: str
    image_url: str | None = None
    year: int | None = None
    creator: str | None = None
    genres: list[str] = []
    description: str | None = None
    external_url: str | None = None
    watch_providers: list[dict] | None = None


class MediaEntryCreate(BaseModel):
    external_id: str
    source: str
    title: str
    media_type: str
    image_url: str | None = None
    year: int | None = None
    creator: str | None = None
    genres: str | None = None
    description: str | None = None
    status: str = "consumed"
    rating: float | None = None
    notes: str | None = None
    tags: str | None = None


class MediaEntryUpdate(BaseModel):
    status: str | None = None
    rating: float | None = None
    notes: str | None = None
    tags: str | None = None


class MediaEntryResponse(BaseModel):
    id: int
    external_id: str
    source: str
    title: str
    media_type: str
    image_url: str | None = None
    year: int | None = None
    creator: str | None = None
    genres: str | None = None
    description: str | None = None
    status: str
    rating: float | None = None
    notes: str | None = None
    tags: str | None = None
    consumed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecommendRequest(BaseModel):
    message: str
    media_type: str | None = None
    history: list[dict] = []


class ProfileStats(BaseModel):
    total_entries: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    avg_rating: float | None
    top_genres: list[str]
