"""Application settings, loaded from environment variables / ``.env``.

Uses pydantic-settings so values are validated and typed. Environment variable
names are matched case-insensitively (``database_url`` <- ``DATABASE_URL``).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application -------------------------------------------------------
    project_name: str = "Judiciary Help System"
    version: str = "0.1.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # -- Database ----------------------------------------------------------
    database_url: str = "sqlite:///./judiciary_help.db"
    sql_echo: bool = False

    # -- Security ----------------------------------------------------------
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # -- CORS --------------------------------------------------------------
    # Raw comma-separated string; use ``cors_origins_list`` for the parsed list.
    cors_origins: str = "*"

    # -- Judiciary scraper -------------------------------------------------
    judiciary_base_url: str = "https://causelist.judiciary.gov.bd"
    judiciary_min_interval: float = 1.0
    judiciary_timeout: float = 20.0
    # Default locality/court used when a lookup request omits them.
    judiciary_default_district: str = "Chandpur"
    judiciary_default_court: str = "চীফ জুডিসিয়াল"
    # How long a cached case lookup stays fresh (minutes).
    judiciary_cache_ttl_minutes: int = 360
    # Raw-HTTP response cache (see app.services.http_cache): master data is
    # cached ~30 days, today's cause list 30 minutes, caseinfo 24 hours.
    judiciary_http_cache_enabled: bool = True
    judiciary_http_cache_capacity: int = 256

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Railway/Heroku emit ``postgres://``; SQLAlchemy 2.x needs a driver."""
        value = value.strip()
        if value.startswith("postgres://"):
            value = value.replace("postgres://", "postgresql+psycopg2://", 1)
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        """``cors_origins`` split into a list of origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()


settings = get_settings()
