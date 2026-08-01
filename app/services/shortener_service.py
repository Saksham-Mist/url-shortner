"""Business logic for creating short URLs, resolving redirects, recording clicks, and computing stats."""
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory
from app.models.url import Click, Url
from app.schemas import ClicksByDay, ReferrerCount, StatsResponse

settings = get_settings()

_BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_CODE_SPACE = 62**settings.short_code_length

# Multiplier used to permute sequential row ids before encoding, so short
# codes don't visibly reveal creation order or total row count. It must share
# no common factors with 62 (= 2 * 31) for the permutation to stay a
# collision-free bijection over the id space; this constant is odd and not a
# multiple of 31, so gcd(multiplier, 62**n) == 1.
_PERMUTATION_MULTIPLIER = 2_654_435_761


def _encode_base62(number: int) -> str:
    """Encode a non-negative integer as a fixed-length Base62 string.

    Right-justified/truncated to settings.short_code_length so every
    short_code has a uniform length regardless of the underlying id's size.
    """
    if number == 0:
        digits = "0"
    else:
        chars: list[str] = []
        remaining = number
        while remaining > 0:
            remaining, remainder = divmod(remaining, 62)
            chars.append(_BASE62_ALPHABET[remainder])
        digits = "".join(reversed(chars))
    return digits.rjust(settings.short_code_length, "0")[-settings.short_code_length :]


def _generate_short_code(row_id: int) -> str:
    """Derive a collision-free short code from a row's primary key.

    Because row_id comes from a BIGSERIAL primary key, two different rows can
    never produce the same code -- uniqueness is structural, not
    probabilistic, so no retry/collision-handling logic is needed anywhere in
    this service.
    """
    permuted = (row_id * _PERMUTATION_MULTIPLIER) % _CODE_SPACE
    return _encode_base62(permuted)


async def create_short_url(db: AsyncSession, long_url: str) -> Url:
    """Create and persist a new shortened URL, returning the saved row.

    Pulls the row's id from its backing sequence *before* inserting, via
    `nextval()`, so short_code can be derived and written in a single INSERT
    alongside id and long_url -- no separate UPDATE, and no retry loop,
    because two different sequence values can never collide.
    """
    next_id_result = await db.execute(text("SELECT nextval('urls_id_seq')"))
    next_id = next_id_result.scalar_one()

    url = Url(id=next_id, short_code=_generate_short_code(next_id), long_url=long_url)
    db.add(url)
    await db.commit()
    await db.refresh(url)
    return url


async def get_active_url_by_code(db: AsyncSession, short_code: str) -> Url | None:
    """Look up a URL by its short code, returning None if missing, inactive, or expired."""
    result = await db.execute(
        select(Url).where(Url.short_code == short_code, Url.is_active.is_(True))
    )
    url = result.scalar_one_or_none()
    if url is None:
        return None
    if url.expires_at is not None and url.expires_at < datetime.now(timezone.utc):
        return None
    return url


async def record_click(url_id: int, request: Request) -> None:
    """Persist a click event for a redirect.

    Deliberately opens its own DB session via async_session_factory instead
    of reusing the request's session. This function runs as a FastAPI
    BackgroundTask, which executes after the response has already been sent
    -- by then the request-scoped session from Depends(get_db) may already be
    closed, so background tasks that touch the DB must create a fresh session.
    """
    async with async_session_factory() as db:
        click = Click(
            url_id=url_id,
            referrer=request.headers.get("referer"),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.add(click)
        await db.commit()


async def get_stats(db: AsyncSession, short_code: str) -> StatsResponse | None:
    """Compute total clicks, clicks-per-day, and top referrers for a short code.

    Returns None if the short code doesn't exist, letting the route decide
    how to translate that into an HTTP response (404).
    """
    url_result = await db.execute(select(Url).where(Url.short_code == short_code))
    url = url_result.scalar_one_or_none()
    if url is None:
        return None

    total_result = await db.execute(
        select(func.count()).select_from(Click).where(Click.url_id == url.id)
    )
    total_clicks = total_result.scalar_one()

    day_column = func.date(Click.clicked_at)
    by_day_result = await db.execute(
        select(day_column.label("day"), func.count().label("clicks"))
        .where(Click.url_id == url.id)
        .group_by(day_column)
        .order_by(day_column)
    )
    clicks_by_day = [ClicksByDay(day=row.day, clicks=row.clicks) for row in by_day_result.all()]

    referrer_result = await db.execute(
        select(Click.referrer, func.count().label("clicks"))
        .where(Click.url_id == url.id)
        .group_by(Click.referrer)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_referrers = [
        ReferrerCount(referrer=row.referrer, clicks=row.clicks) for row in referrer_result.all()
    ]

    return StatsResponse(
        short_code=url.short_code,
        total_clicks=total_clicks,
        clicks_by_day=clicks_by_day,
        top_referrers=top_referrers,
    )
