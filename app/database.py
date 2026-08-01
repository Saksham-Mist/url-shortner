"""Async SQLAlchemy engine and per-request session management."""
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# Managed Postgres providers (Neon, RDS, etc.) require TLS. asyncpg has no
# concept of the `sslmode` query param used by libpq-based drivers, so SSL is
# enabled here via connect_args instead of being embedded in the URL itself.
_connect_args = {"ssl": True} if settings.db_requires_ssl else {}

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    """Base class for all ORM models; Base.metadata is what create_all()/Alembic operate on."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one AsyncSession per request and closes it afterward."""
    async with async_session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
