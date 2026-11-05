from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", case_sensitive=False)
    database_url: SecretStr = SecretStr("sqlite:///data/learnloop.db")
    api_token: SecretStr = SecretStr("")
    local_owner_id: str = "local-owner"
    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "bge-m3"
    ollama_embedding_endpoint: str = "/api/embed"
    embedding_dimensions: int = Field(default=1024, gt=0)
    qdrant_url: str = ""
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection: str = "learnloop"
    qdrant_verify_ssl: bool = True
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )
    llm_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENROUTER_API_KEY")
    llm_model: str = Field(default="openai/gpt-6-luna", validation_alias="OPENROUTER_MODEL")
    request_timeout_seconds: int = Field(default=90, ge=1, le=300)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=200, ge=1)
    max_chunks: int = Field(default=1000, ge=1)
    worker_lease_seconds: int = Field(default=1800, ge=300)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    expert_material_workers: int = Field(default=6, ge=1, le=12)

    @field_validator("database_url", mode="after")
    @classmethod
    def resolve_sqlite_path(cls, value):
        from sqlalchemy.engine import make_url

        url = make_url(value.get_secret_value())
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            path = Path(url.database)
            if not path.is_absolute():
                url = url.set(database=str((ROOT / path).resolve()))
            return SecretStr(url.render_as_string(hide_password=False))
        return value

    @property
    def uses_sqlite(self) -> bool:
        return self.database_url.get_secret_value().startswith("sqlite:")

    @property
    def generation_ready(self) -> bool:
        return bool(self.llm_base_url and self.llm_model and self.llm_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
