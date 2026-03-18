from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_happy_path_cancel_and_email(transport):
    """Full success: cancel works, email fires, response is SUCCESS."""
    with patch("app.tools.random.random", return_value=0.99):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/process", json={
                "request": "Cancel order #9921 and email user@example.com"
            })

    data = resp.json()
    assert resp.status_code == 200
    assert data["status"] == "SUCCESS"
    assert len(data["steps_executed"]) == 2
    assert data["steps_executed"][0]["tool"] == "cancel_order"
    assert data["steps_executed"][0]["status"] == "SUCCESS"
    assert data["steps_executed"][1]["tool"] == "send_email"
    assert data["steps_executed"][1]["status"] == "SUCCESS"
    assert data["error"] is None


@pytest.mark.asyncio
async def test_cancel_failure_blocks_email(transport):
    """When cancel_order fails, send_email must be SKIPPED."""
    with patch("app.tools.random.random", return_value=0.01):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/process", json={
                "request": "Cancel order #5500 and email me at user@test.com"
            })

    data = resp.json()
    assert resp.status_code == 200
    assert data["status"] == "FAILED"
    assert data["steps_executed"][0]["tool"] == "cancel_order"
    assert data["steps_executed"][0]["status"] == "FAILED"
    assert data["steps_executed"][1]["tool"] == "send_email"
    assert data["steps_executed"][1]["status"] == "SKIPPED"
    assert data["error"] is not None


@pytest.mark.asyncio
async def test_missing_order_id(transport):
    """Cancel intent without an order number should fail at planning."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/process", json={
            "request": "Cancel my order please"
        })

    data = resp.json()
    assert resp.status_code == 200
    assert data["status"] == "PLANNING_FAILED"
    assert "order" in data["error"].lower()


@pytest.mark.asyncio
async def test_missing_email_address(transport):
    """Email intent without an address should fail at planning."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/process", json={
            "request": "Cancel order #1234 and email the confirmation"
        })

    data = resp.json()
    assert resp.status_code == 200
    assert data["status"] == "PLANNING_FAILED"
    assert "email" in data["error"].lower()


@pytest.mark.asyncio
async def test_malformed_input(transport):
    """Completely unrecognizable input returns PLANNING_FAILED."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/process", json={
            "request": "asdfghjkl zxcvbnm"
        })

    data = resp.json()
    assert resp.status_code == 200
    assert data["status"] == "PLANNING_FAILED"
    assert data["error"] is not None


@pytest.mark.asyncio
async def test_empty_request_rejected(transport):
    """Empty string should be rejected by Pydantic validation."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/process", json={"request": ""})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cancel_only_no_email(transport):
    """Cancel without email intent should produce a single-step plan."""
    with patch("app.tools.random.random", return_value=0.99):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/process", json={
                "request": "Please cancel order #7777"
            })

    data = resp.json()
    assert resp.status_code == 200
    assert data["status"] == "SUCCESS"
    assert len(data["steps_executed"]) == 1
    assert data["steps_executed"][0]["tool"] == "cancel_order"


@pytest.mark.asyncio
async def test_response_includes_request_id(transport):
    """Every response should carry a unique request_id."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post("/process", json={
            "request": "Cancel order #1111"
        })
        r2 = await client.post("/process", json={
            "request": "Cancel order #2222"
        })

    assert r1.json()["request_id"] != r2.json()["request_id"]
