from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    google_api_key: str = ""
    database_url: str = ""
    cors_origins: str = "http://localhost:3000"
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_live_model: str = "gemini-3.8-live"
    gemini_embedding_model: str = "models/gemini-embedding-001"
    pgvector_collection: str = "slt_mobitel_knowledge"
    gemini_temperature: float = 0.2
    gemini_top_p: float = 0.95
    gemini_max_output_tokens: int = 1024
    gemini_thinking_level: str = "medium"
    gemini_request_timeout: float = 30.0

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
