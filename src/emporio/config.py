from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""
    typesafe_api_key: str = ""
    llm_model: str = "google:gemini-4-hydrogen"
    jev_model: str = "jev-latest"
    jev_api_url: str = "https://api.typesafe.ai/v1/systemone"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    raw_data_dir: Path = Path("data/raw")
    database_path: Path = Path("data/emporio.db")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auth_secret: str = "dev-emporio-change-me-in-prod"
    seed_admin_email: str = "admin@admin.com"
    seed_admin_password: str = "admin123"
    seed_user_email: str = "user@user.com"
    seed_user_password: str = "user123"
    order_auto_delivery_seconds: int = 300
    rate_limit_chat_per_minute: int = 20
    rate_limit_auth_per_minute: int = 15

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
