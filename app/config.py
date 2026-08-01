"""Application configuration, loaded once from environment variables / .env."""
import re
from functools import lru_cache

from pydantic import Field, ValidationError
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
    """Return a process-wide cached Settings instance so .env is only parsed once.

    Deliberately still fails immediately at first call (import time, via
    database.py's module-level `settings = get_settings()`) if DATABASE_URL
    is missing, rather than deferring validation until a request tries to
    use the DB. A required secret with no sane default should crash loudly
    at boot, not accept traffic and fail unpredictably on the first query --
    and on Railway (or any container platform), env vars are injected before
    the process starts, so "missing at import time" and "missing five
    minutes later" are the same failure, not a race. This wrapper only
    replaces pydantic's generic ValidationError with a message that says
    what to actually go check.
    """
    try:
        return Settings()
    except ValidationError as exc:
        missing_fields = {
            str(error["loc"][0]) for error in exc.errors() if error["type"] == "missing"
        }
        if "raw_database_url" in missing_fields or "DATABASE_URL" in missing_fields:
            raise RuntimeError(
                "DATABASE_URL is not set in this environment. On Railway this "
                "is almost always a configuration gap, not a startup-timing "
                "issue -- env vars are injected before your process starts. "
                "Check: (1) Railway dashboard -> this service -> Variables "
                "tab actually has DATABASE_URL (Railway only auto-populates "
                "it for its own managed Postgres plugin -- an external DB "
                "like Neon must be added manually), (2) it's set on *this* "
                "service/environment and not a different one in the project, "
                "(3) you redeployed after adding it."
            ) from exc
        raise
