"""API routes: create short URLs, redirect to them, and read click stats.

One router, full paths per-route (rather than a shared APIRouter prefix),
because GET /{short_code} deliberately lives at the root while the other two
endpoints live under /api/v1 -- a single prefix couldn't express both.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.database import DbSession
from app.schemas import ShortenRequest, ShortenResponse, StatsResponse
from app.services import shortener_service

router = APIRouter()
settings = get_settings()


@router.post("/api/v1/shorten", response_model=ShortenResponse, status_code=status.HTTP_201_CREATED)
async def shorten_url(body: ShortenRequest, db: DbSession) -> ShortenResponse:
    """Create a new shortened URL for the given long URL.

    201 (not 200) because a new resource is created. Invalid URLs never reach
    this body -- Pydantic's HttpUrl validation rejects them with 422 before
    this function is even called.
    """
    url = await shortener_service.create_short_url(db, str(body.long_url))
    return ShortenResponse(
        short_code=url.short_code,
        short_url=f"{settings.base_url}/{url.short_code}",
    )


@router.get("/api/v1/stats/{short_code}", response_model=StatsResponse)
async def get_url_stats(short_code: str, db: DbSession) -> StatsResponse:
    """Return total clicks, clicks per day, and top referrers for a short code."""
    stats = await shortener_service.get_stats(db, short_code)
    if stats is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short code not found")
    return stats


@router.get("/{short_code}")
async def redirect_to_long_url(
    short_code: str,
    request: Request,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Redirect to the original long URL and log the click without blocking the response.

    Uses a 302 (temporary) redirect, deliberately not 301: a 301 gets cached
    by browsers, which would skip hitting this server on repeat visits --
    breaking click tracking and making it impossible to deactivate or repoint
    the link later.

    The click is recorded via BackgroundTasks so the redirect itself doesn't
    wait on a DB write; the user should never feel the cost of analytics.
    """
    url = await shortener_service.get_active_url_by_code(db, short_code)
    if url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short code not found")

    background_tasks.add_task(shortener_service.record_click, url.id, request)
    return RedirectResponse(url=str(url.long_url), status_code=status.HTTP_302_FOUND)
