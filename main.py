"""FastAPI application entry point."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import Base, engine
from app.routes.shorten import router as shorten_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create tables on startup.

    Dev convenience only. In production, schema changes should go through
    Alembic migrations instead of create_all(), so changes are versioned and
    reviewable rather than silently applied on every boot.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="URL Shortener", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness endpoint for uptime checks / load balancers.

    Registered before shorten_router is included: FastAPI matches routes in
    registration order, and shorten_router's catch-all GET /{short_code}
    would otherwise swallow /health (treating "health" as a short code).
    """
    return {"status": "ok"}


app.include_router(shorten_router)
