"""
WebSocket tests for Louise (FastAPI server).
Uses sync TestClient fixture from conftest for websocket_connect.
"""

import pytest


def test_websocket_connect(client):
    """WebSocket /ws accepts connection."""
    with client.websocket_connect("/ws") as ws:
        # Connection accepted; receive optional mission_update if mission was planned
        pass


def test_websocket_ping_pong(client):
    """Send ping, receive pong. Drain any initial mission_update from prior tests."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ping"})
        for _ in range(5):
            data = ws.receive_json()
            if data.get("type") == "pong":
                break
        else:
            pytest.fail("Did not receive pong")


def test_websocket_malformed_json(client):
    """Send malformed JSON. Server should respond with error and NOT disconnect."""
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not json")
        for _ in range(5):
            data = ws.receive_json()
            if data.get("type") == "error":
                assert "Invalid JSON" in data.get("message", "")
                break
            if data.get("type") == "pong":
                pytest.fail("Got pong instead of error")
        else:
            pytest.fail("Did not receive error response for malformed JSON")


def test_websocket_user_position_no_exception(client):
    """Send user_position with lat/lng; assert no exception. Drain initial messages then ping/pong."""
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_position", "lat": 48.86, "lng": 2.34})
        ws.send_json({"type": "ping"})
        for _ in range(5):
            data = ws.receive_json()
            if data.get("type") == "pong":
                break
        else:
            pytest.fail("Did not receive pong after user_position")


def test_websocket_emergency_broadcast(client):
    """
    First client sends emergency; second client should receive broadcast.
    We use two connections: one to send emergency, one to receive the broadcast.
    Receiver may get mission_update first if a mission was planned in a previous test.
    """
    with client.websocket_connect("/ws") as ws_sender:
        with client.websocket_connect("/ws") as ws_receiver:
            ws_sender.send_json({"type": "emergency", "origin": "test"})
            # Receiver may get mission_update first; receive until we get emergency
            for _ in range(5):
                received = ws_receiver.receive_json()
                if received.get("type") == "emergency":
                    assert received.get("origin") == "test"
                    break
            else:
                pytest.fail("Did not receive emergency broadcast")
