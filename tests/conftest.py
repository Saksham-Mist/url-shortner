import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

"""Shared pytest fixtures for the API test suite.

NOTE: these fixtures target DATABASE_URL from .env -- the same live Neon
database the app uses in dev, not a separate test database. That's a
deliberate, temporary simplification: `_clean_database` truncates `urls` and
`clicks` before *and* after every single test. A dedicated TEST_DATABASE_URL
(e.g. wired up in CI) is a planned follow-up; until then, don't run this
suite against a database whose data you want to keep.
"""
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.database import engine
from main import app


@pytest_asyncio.fixture(autouse=True)
async def _clean_database() -> AsyncIterator[None]:
    """Truncate urls/clicks before and after every test.

    RESTART IDENTITY also resets the urls_id_seq sequence backing urls.id.
    That matters specifically because short_code is derived from the row id
    (see shortener_service._generate_short_code) -- without resetting it,
    the codes a test observes would depend on how many rows earlier tests
    (or earlier runs) happened to create. CASCADE clears clicks in the same
    statement via its foreign key to urls.
    """
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE clicks, urls RESTART IDENTITY CASCADE"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE clicks, urls RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An httpx.AsyncClient wired directly to the FastAPI app over ASGI (no real socket/server)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
