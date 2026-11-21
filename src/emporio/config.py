"""Configuração tipada da aplicação carregada de variáveis de ambiente."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parâmetros de execução da API, banco local e provedor Gemini."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(default="", description="Chave da API do Google Gemini.")
    llm_model: str = Field(
        default="google:gemini-4-hydrogen",
        description="Identificador do modelo no formato provider:model do PydanticAI.",
    )
    embedding_model: str = Field(
        default="gemini-embedding-001",
        description="Modelo de embeddings usado na indexação opcional das políticas.",
    )
    raw_data_dir: Path = Field(
        default=Path("data/raw"),
        description="Diretório com os CSVs e PDF originais da loja (somente leitura).",
    )
    database_path: Path = Field(
        default=Path("data/emporio.db"),
        description="Caminho do banco SQLite gerado pelo ETL.",
    )
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
