import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Explicitly load .env before anything else reads env vars
load_dotenv(BASE_DIR / ".env", override=True)


class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    tmdb_api_key: str = os.getenv("TMDB_API_KEY", "")
    google_books_api_key: str = os.getenv("GOOGLE_BOOKS_API_KEY", "")
    nyt_api_key: str = os.getenv("NYT_API_KEY", "")
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    secret_key: str = os.getenv("SECRET_KEY", "nextup-dev-secret-change-in-production")
    jwt_secret: str = os.getenv("JWT_SECRET", "nextup-dev-jwt-secret-change-in-production")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/rec.db")
    admin_email: str = os.getenv("ADMIN_EMAIL", "")
    # When True, only admin + emails in allowed_emails table can log in.
    # Set INVITE_ONLY=true in .env to enable.
    invite_only: bool = os.getenv("INVITE_ONLY", "false").lower() == "true"


settings = Settings()

# Set GOOGLE_API_KEY so the Gemini SDK can find it
if settings.gemini_api_key:
    os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
