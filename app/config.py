"""Application configuration, loaded once from environment variables / .env."""
import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized app settings. Values come from environment variables or a .env file."""

    raw_database_url: str = Field(alias="DATABASE_URL")
    base_url: str = "http://localhost:8000"
    short_code_length: int = 7
    sql_echo: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """Return DATABASE_URL rewritten for the async driver.

        The value in .env is a standard libpq URL (`postgresql://...`) with a
        `sslmode=require` query param, e.g. from Neon/RDS. `asyncpg` doesn't
        understand `sslmode` (it's a libpq/psycopg2 concept) and will raise a
        connect error if it's left in the URL, so it's stripped here. SSL is
        turned on separately via `connect_args` in database.py.
        """
        url = self.raw_database_url
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        return re.sub(r"[?&]sslmode=[^&]*", "", url)

    @property
    def db_requires_ssl(self) -> bool:
        """Whether the original DATABASE_URL requested SSL (true for Neon, RDS, etc.)."""
        return "sslmode=require" in self.raw_database_url


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance so .env is only parsed once."""
    return Settings()
