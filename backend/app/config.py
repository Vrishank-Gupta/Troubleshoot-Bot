from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = ""

    # Supabase (optional — used to derive database_url if database_url not set)
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_anon_key: str = ""

    # LLM
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Cache — empty string = no Redis, use in-memory fallback
    redis_url: str = ""
    cache_ttl_sops: int = 300        # seconds to cache published SOP flows
    cache_ttl_products: int = 600    # seconds to cache product/hierarchy list

    # Runtime
    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-in-production"

    # Limits
    llm_timeout: int = 30
    llm_max_retries: int = 2         # reduced — fast-fail, not retry-storm
    search_top_k: int = 5
    clarification_threshold: float = 0.75
    max_retry_per_step: int = 2

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    @property
    def pg_dsn(self) -> str:
        if self.database_url:
            return self.database_url
        if self.supabase_url and self.supabase_service_role_key:
            ref = self.supabase_url.replace("https://", "").split(".")[0]
            return (
                f"postgresql://postgres.{ref}:{self.supabase_service_role_key}"
                f"@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
            )
        return "postgresql://postgres:postgres@localhost:5432/chatbot"


@lru_cache
def get_settings() -> Settings:
    return Settings()
