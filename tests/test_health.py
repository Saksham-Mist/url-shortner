"""Tests for the liveness/health check endpoint."""
from httpx import AsyncClient


async def test_health_check_returns_ok(client: AsyncClient) -> None:
    """GET /health returns 200 with a simple status payload and touches no database state."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
