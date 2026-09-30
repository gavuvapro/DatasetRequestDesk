"""Application settings loaded from environment variables (12-factor style)."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database ---------------------------------------------------------------
    database_url: str = "postgresql+psycopg2://drd:drd@db:5432/dataset_request_desk"

    # JWT --------------------------------------------------------------------
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    # Seeding ----------------------------------------------------------------
    seed_users_file: str = "seed/users.json"

    # Logging ----------------------------------------------------------------
    log_format: str = "json"  # "json" | "text"
    log_level: str = "INFO"

    # Known robots accepted by the CSV import engine.
    known_robots: list[str] = ["arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"]

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalise_driver(cls, url: str) -> str:
        """Accept bare `postgresql://` (Neon's default) and map it to psycopg2.

        Also transparently supports `postgres://` scheme as some hosts emit it.
        """
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg2://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url

    @property
    def sync_database_url(self) -> str:
        """URL for sync engines (SQLAlchemy / Alembic). psycopg2 everywhere."""
        return self.database_url

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
