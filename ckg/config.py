"""Centralized settings loaded from environment / .env."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # API
    api_host: str = Field("0.0.0.0", alias="CKG_API_HOST")
    api_port: int = Field(8080, alias="CKG_API_PORT")
    log_level: str = Field("INFO", alias="CKG_LOG_LEVEL")
    cors_origins: str = Field("http://localhost:3000,http://localhost:8080", alias="CKG_CORS_ORIGINS")
    bootstrap_token: str = Field(..., alias="CKG_BOOTSTRAP_TOKEN")
    secret_key: str = Field(..., alias="CKG_SECRET_KEY")

    # Neo4j
    neo4j_uri: str = Field("bolt://neo4j:7687", alias="NEO4J_URI")
    neo4j_user: str = Field("neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(..., alias="NEO4J_PASSWORD")
    neo4j_database: str = Field("neo4j", alias="NEO4J_DATABASE")

    # Postgres
    postgres_host: str = Field("postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("ckg", alias="POSTGRES_DB")
    postgres_user: str = Field("ckg", alias="POSTGRES_USER")
    postgres_password: str = Field(..., alias="POSTGRES_PASSWORD")

    # Redis / Celery
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field("redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field("redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")

    # Embeddings
    embedding_model: str = Field("sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(384, alias="EMBEDDING_DIM")

    # Repo storage
    repo_root: str = Field("/var/lib/ckg/repos", alias="CKG_REPO_ROOT")

    # Language filter
    enabled_languages: str = Field(
        "python,javascript,typescript,rust,go,java,ruby,c,cpp,"
        "csharp,kotlin,scala,swift,php,solidity,dart,"
        "r,perl,lua,zig,powershell,julia,nix,"
        "vue,svelte,ipynb",
        alias="CKG_ENABLED_LANGUAGES",
    )

    # LSP precision pass (opt-in)
    lsp_enabled: bool = Field(False, alias="CKG_LSP_ENABLED")
    lsp_adapters: str = Field("", alias="CKG_LSP_ADAPTERS")  # csv of languages; empty = all available

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_language_list(self) -> list[str]:
        return [lang.strip().lower() for lang in self.enabled_languages.split(",") if lang.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
