"""FastAPI application entry point."""
from fastapi import FastAPI

from app.routes.shorten import router as shorten_router

# Schema is owned by Alembic (see migrations/), not by the app at startup:
# run `alembic upgrade head` to create/update tables. No create_all() call
# here on purpose -- that would apply schema changes silently on every boot
# instead of via versioned, reviewable migrations.
app = FastAPI(title="URL Shortener", version="1.0.0")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness endpoint for uptime checks / load balancers.

    Registered before shorten_router is included: FastAPI matches routes in
    registration order, and shorten_router's catch-all GET /{short_code}
    would otherwise swallow /health (treating "health" as a short code).
    """
    return {"status": "ok"}


app.include_router(shorten_router)
