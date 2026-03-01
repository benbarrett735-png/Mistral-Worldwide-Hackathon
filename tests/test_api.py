"""
API endpoint tests for Louise (FastAPI server).
Uses async_client fixture from conftest (httpx.AsyncClient with ASGITransport).
"""

import pytest

from server import _TEST_FRAME_B64


@pytest.mark.asyncio
async def test_get_root_returns_307(async_client):
    """GET / redirects to /user (307)."""
    response = await async_client.get("/")
    assert response.status_code == 307
    assert response.headers.get("location", "").endswith("/user")


@pytest.mark.asyncio
async def test_get_test_frame_returns_200_and_jpeg(async_client):
    """GET /api/test-frame returns 200 and image/jpeg."""
    response = await async_client.get("/api/test-frame")
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("image/jpeg")
    assert len(response.content) > 0


@pytest.mark.asyncio
async def test_get_health_returns_200(async_client):
    """GET /health returns 200."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_post_route_returns_200_and_coords(async_client):
    """POST /api/route with origin and destination returns 200 and coords."""
    response = await async_client.post(
        "/api/route",
        json={
            "origin": [48.86, 2.34],
            "destination": [48.85, 2.36],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "coords" in data
    assert isinstance(data["coords"], list)
    assert len(data["coords"]) >= 2


@pytest.mark.asyncio
async def test_post_order_returns_200_and_status_planned(async_client):
    """POST /api/order with origin and destination returns 200 and status planned."""
    response = await async_client.post(
        "/api/order",
        json={
            "origin": [48.86, 2.34],
            "destination": [48.85, 2.36],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "planned"


@pytest.mark.asyncio
async def test_post_helpstral_returns_200_and_status(async_client):
    """POST /api/helpstral with base64 image returns 200 and status key."""
    response = await async_client.post(
        "/api/helpstral",
        json={"image": _TEST_FRAME_B64},
    )
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_post_flystral_returns_200_and_command(async_client):
    """POST /api/flystral with base64 image returns 200 and command key."""
    response = await async_client.post(
        "/api/flystral",
        json={"image": _TEST_FRAME_B64},
    )
    assert response.status_code == 200
    data = response.json()
    assert "command" in data


@pytest.mark.asyncio
async def test_get_config_returns_200(async_client):
    """GET /api/config returns hub, bounds, pricing."""
    response = await async_client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "hub" in data
    assert "bounds" in data
    assert "base_price_eur" in data
    assert "price_per_km_eur" in data


@pytest.mark.asyncio
async def test_post_estimate_returns_200(async_client):
    """POST /api/estimate returns distance_km and estimate_eur."""
    response = await async_client.post(
        "/api/estimate",
        json={"origin": [48.86, 2.34], "destination": [48.85, 2.36]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "distance_km" in data
    assert "estimate_eur" in data
    assert data["estimate_eur"] >= 0


@pytest.mark.asyncio
async def test_post_route_outside_bounds_returns_400(async_client):
    """POST /api/route with origin/destination outside geofence returns 400."""
    response = await async_client.post(
        "/api/route",
        json={"origin": [0, 0], "destination": [1, 1]},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_post_order_when_mission_in_progress_auto_cancels(async_client, monkeypatch):
    """POST /api/order auto-cancels any in-progress mission and replans."""
    import server as server_module
    monkeypatch.setattr(server_module, "_mission_in_progress", True)
    response = await async_client.post(
        "/api/order",
        json={"origin": [48.86, 2.34], "destination": [48.85, 2.36]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "planned"
    monkeypatch.setattr(server_module, "_mission_in_progress", False)
