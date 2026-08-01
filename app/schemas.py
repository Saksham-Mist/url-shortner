"""Pydantic request/response models -- the API contract, kept independent of the ORM models."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ShortenRequest(BaseModel):
    """Request body for POST /api/v1/shorten."""

    long_url: HttpUrl = Field(..., alias="longUrl", description="The original URL to shorten.")

    model_config = ConfigDict(populate_by_name=True)


class ShortenResponse(BaseModel):
    """Response body for POST /api/v1/shorten."""

    short_code: str = Field(..., alias="shortCode")
    short_url: HttpUrl = Field(..., alias="shortUrl")

    model_config = ConfigDict(populate_by_name=True)


class ClicksByDay(BaseModel):
    """Click count for a single calendar day; one entry in StatsResponse.clicks_by_day."""

    day: date
    clicks: int


class ReferrerCount(BaseModel):
    """Click count grouped by referrer; one entry in StatsResponse.top_referrers."""

    referrer: str | None
    clicks: int


class StatsResponse(BaseModel):
    """Response body for GET /api/v1/stats/{shortCode}."""

    short_code: str = Field(..., alias="shortCode")
    total_clicks: int = Field(..., alias="totalClicks")
    clicks_by_day: list[ClicksByDay] = Field(..., alias="clicksByDay")
    top_referrers: list[ReferrerCount] = Field(..., alias="topReferrers")

    model_config = ConfigDict(populate_by_name=True)
