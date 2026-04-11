from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    tmdb_api_key: str = ""
    google_books_api_key: str = ""
    database_url: str = "sqlite:///./rec.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
