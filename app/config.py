from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    gemini_api_key: str = ""
    tmdb_api_key: str = ""
    google_books_api_key: str = ""
    database_url: str = f"sqlite:///{BASE_DIR}/rec.db"

    model_config = {"env_file": str(BASE_DIR / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
