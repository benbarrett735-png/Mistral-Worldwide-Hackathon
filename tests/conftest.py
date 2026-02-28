"""
Pytest configuration and shared fixtures for Louise API tests.
Uses pytest-asyncio for async tests; httpx AsyncClient for HTTP; TestClient for WebSocket.
"""

import pytest

pytest_plugins = ("pytest_asyncio",)
import httpx
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def app_fixture():
    """FastAPI app instance."""
    return app


@pytest.fixture
async def async_client(app_fixture):
    """Async HTTP client for testing API endpoints (uses ASGI transport)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_fixture),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def client(app_fixture):
    """Synchronous TestClient for WebSocket and sync HTTP (e.g. follow_redirects)."""
    return TestClient(app_fixture)
