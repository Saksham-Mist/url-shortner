"""Tests for POST /api/v1/shorten, GET /{shortCode}, and GET /api/v1/stats/{shortCode}."""
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import HttpUrl

from app.config import get_settings
from app.services.shortener_service import _generate_short_code

settings = get_settings()


async def _create_short_url(client: AsyncClient, long_url: str) -> dict[str, Any]:
    """POST /api/v1/shorten and return the parsed JSON body. Shared setup step for tests below."""
    response = await client.post("/api/v1/shorten", json={"longUrl": long_url})
    assert response.status_code == 201, response.text
    return response.json()


async def test_shorten_valid_url_returns_201(client: AsyncClient) -> None:
    """A well-formed http(s) URL is accepted, creating a new resource (201) with a shortCode/shortUrl pair."""
    response = await client.post(
        "/api/v1/shorten",
        json={"longUrl": "https://example.com/articles/123?utm_source=test"},
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body.keys()) == {"shortCode", "shortUrl"}
    assert len(body["shortCode"]) == settings.short_code_length
    assert body["shortCode"].isalnum()  # base62: letters + digits only, no other characters
    assert body["shortUrl"].endswith(body["shortCode"])


@pytest.mark.parametrize(
    "invalid_long_url",
    [
        pytest.param("not-a-url", id="no-scheme"),
        pytest.param("", id="empty-string"),
        pytest.param("ftp://example.com/file", id="disallowed-scheme-ftp"),
        pytest.param("javascript:alert(1)", id="disallowed-scheme-javascript"),
    ],
)
async def test_shorten_invalid_url_rejected(client: AsyncClient, invalid_long_url: str) -> None:
    """Malformed URLs and disallowed schemes are rejected with 422 before any DB write happens.

    Pydantic's HttpUrl type only accepts http/https schemes, so the ftp/
    javascript cases here double as a regression test for the scheme
    restriction that guards against open-redirect / scheme-injection abuse
    (a submitted "long_url" must never reach storage as javascript:... etc).
    """
    response = await client.post("/api/v1/shorten", json={"longUrl": invalid_long_url})

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert any("longUrl" in error["loc"] for error in body["detail"])


async def test_redirect_to_existing_short_code(client: AsyncClient) -> None:
    """GET /{shortCode} responds 302 with a Location header pointing back at the original URL."""
    long_url = "https://example.com/docs/getting-started"
    created = await _create_short_url(client, long_url)

    response = await client.get(f"/{created['shortCode']}", follow_redirects=False)

    assert response.status_code == 302
    # Compare via HttpUrl, not raw strings: Pydantic may normalize the URL on
    # the way in (e.g. add a trailing slash), so a byte-for-byte string
    # comparison against the original input would be a false negative.
    assert HttpUrl(response.headers["location"]) == HttpUrl(long_url)


async def test_redirect_to_nonexistent_code_returns_404(client: AsyncClient) -> None:
    """GET /{shortCode} for a code that was never created returns 404, not a 302 to nowhere."""
    response = await client.get("/doesnotexist", follow_redirects=False)

    assert response.status_code == 404


async def test_stats_returns_correct_click_data(client: AsyncClient) -> None:
    """Stats correctly aggregate total clicks, per-day counts, and per-referrer counts.

    The redirect route logs each click via BackgroundTasks so the redirect
    itself doesn't wait on a DB write (see routes/shorten.py). Under httpx's
    ASGITransport, background tasks run to completion inside the same
    awaited call -- there's no real socket/connection-close boundary like
    against a live uvicorn server -- so no extra wait is needed here before
    asserting on the stats below.
    """
    created = await _create_short_url(client, "https://example.com/pricing")
    short_code = created["shortCode"]

    await client.get(f"/{short_code}", headers={"Referer": "https://google.com"}, follow_redirects=False)
    await client.get(f"/{short_code}", headers={"Referer": "https://google.com"}, follow_redirects=False)
    await client.get(f"/{short_code}", headers={"Referer": "https://twitter.com"}, follow_redirects=False)

    response = await client.get(f"/api/v1/stats/{short_code}")

    assert response.status_code == 200
    body = response.json()
    assert body["shortCode"] == short_code
    assert body["totalClicks"] == 3
    assert len(body["clicksByDay"]) == 1
    assert body["clicksByDay"][0]["clicks"] == 3
    referrer_counts = {row["referrer"]: row["clicks"] for row in body["topReferrers"]}
    assert referrer_counts == {"https://google.com": 2, "https://twitter.com": 1}


async def test_stats_for_nonexistent_code_returns_404(client: AsyncClient) -> None:
    """GET /api/v1/stats/{shortCode} for an unknown code returns 404, not an empty 200."""
    response = await client.get("/api/v1/stats/doesnotexist")

    assert response.status_code == 404


async def test_duplicate_shorten_requests_return_different_codes(client: AsyncClient) -> None:
    """Shortening the same long URL twice creates two independent rows with two different codes.

    There's no dedup-by-long_url logic in create_short_url, and the schema
    has no unique constraint on long_url -- each request is its own link.
    This test locks that behavior in as intentional, so it reads as a
    regression (not a fix) if someone later adds deduping without meaning to
    change the API contract.
    """
    long_url = "https://example.com/same-link-twice"

    first = await _create_short_url(client, long_url)
    second = await _create_short_url(client, long_url)

    assert first["shortCode"] != second["shortCode"]


def test_short_codes_are_collision_free_by_construction() -> None:
    """Short codes can't collide -- by construction, not just "very unlikely to".

    This project generates codes with a counter-based strategy (see
    shortener_service._generate_short_code): each code Base62-encodes a
    permutation of the row's own database-sequence id. The permutation
    multiplier is coprime with the code space (62**short_code_length), which
    makes id -> code a bijection over that space, so two different ids can
    never map to the same code.

    That's a different, stronger guarantee than the *other* common
    strategy -- generate a random string, retry on a UNIQUE violation --
    where collisions are merely improbable (bounded by the birthday
    paradox), not impossible. This codebase uses the counter-based strategy,
    so there's no retry loop to test; instead, this test checks the
    mathematical property that design decision relies on, across a batch of
    ids large enough that a flawed permutation would reliably surface a
    repeat.
    """
    codes = [_generate_short_code(row_id) for row_id in range(20_000)]

    assert len(codes) == len(set(codes))


async def test_creating_many_short_urls_never_collides(client: AsyncClient) -> None:
    """End-to-end confirmation that the real API/DB path never produces a duplicate short_code.

    Complements test_short_codes_are_collision_free_by_construction (which
    tests the pure encoding function in isolation) by exercising the full
    path, including the live urls_id_seq sequence the guarantee actually
    depends on.
    """
    codes = [
        (await _create_short_url(client, f"https://example.com/item/{i}"))["shortCode"]
        for i in range(50)
    ]

    assert len(codes) == len(set(codes))
