from datetime import datetime

from pydantic import BaseModel, Field


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
    backdrop_url: str | None = None
    watch_providers: list[dict] | None = None
    audience_score: float | None = None  # TMDB vote_average (0-10)
    audience_count: int | None = None    # TMDB vote_count
    popularity: float | None = None      # TMDB popularity score
    runtime: int | None = None           # minutes
    status: str | None = None            # "Ended", "Returning Series", etc.
    seasons: int | None = None
    episodes: int | None = None
    network: str | None = None           # primary network name
    signal_score: float | None = None    # 0-10 recommendation strength (predicted_rating * 2)


class TonightPick(BaseModel):
    item: MediaResult
    reason: str = Field(..., max_length=140)
    providers: list[str] = []


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
    rating: float | None = Field(None, ge=1, le=5)
    notes: str | None = None
    tags: str | None = None


class MediaEntryUpdate(BaseModel):
    status: str | None = None
    rating: float | None = Field(None, ge=1, le=5)
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
    rated_at: datetime | None = None
    predicted_rating: float | None = None
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


class DismissedItemCreate(BaseModel):
    external_id: str | None = None
    source: str | None = None
    title: str
    media_type: str


class DismissedItemResponse(BaseModel):
    id: int
    external_id: str | None = None
    source: str | None = None
    title: str
    media_type: str
    created_at: datetime

    model_config = {"from_attributes": True}
