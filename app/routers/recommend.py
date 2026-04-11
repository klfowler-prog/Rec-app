from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import User
from app.schemas import RecommendRequest

router = APIRouter()


@router.post("/")
async def get_recommendations(req: RecommendRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Stream AI-powered recommendations based on the user's taste profile."""
    from app.services.recommendation import stream_recommendation

    return StreamingResponse(
        stream_recommendation(req.message, req.media_type, req.history, db, user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
