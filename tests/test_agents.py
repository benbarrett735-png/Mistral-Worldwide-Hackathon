"""Tests for the multi-agent system: Helpstral, Flystral, Louise agents + agent loop."""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpstral agent tests ────────────────────────────────────────────────────

class TestHelpstralAgent:
    def test_parse_valid_json(self):
        from helpstral.agent import parse_structured_assessment
        raw = json.dumps({
            "threat_level": 3, "status": "SAFE",
            "observations": ["well-lit street", "no pedestrians"],
            "pattern": "Consistent safe", "reasoning": "Normal conditions.",
            "action": "CONTINUE_MONITORING",
        })
        result = parse_structured_assessment(raw)
        assert result["threat_level"] == 3
        assert result["status"] == "SAFE"
        assert len(result["observations"]) == 2

    def test_parse_json_in_markdown(self):
        from helpstral.agent import parse_structured_assessment
        raw = '```json\n{"threat_level": 7, "status": "CAUTION", "observations": ["person following"], "pattern": "Follower detected", "reasoning": "Test.", "action": "INCREASE_SCAN_RATE"}\n```'
        result = parse_structured_assessment(raw)
        assert result["threat_level"] == 7
        assert result["status"] == "CAUTION"

    def test_parse_embedded_json(self):
        from helpstral.agent import parse_structured_assessment
        raw = 'Here is the assessment: {"threat_level": 5, "status": "CAUTION"} end'
        result = parse_structured_assessment(raw)
        assert result["threat_level"] == 5

    def test_parse_garbage_returns_default(self):
        from helpstral.agent import parse_structured_assessment
        result = parse_structured_assessment("just some random text no json here")
        assert result["status"] == "SAFE"
        assert result.get("parse_error") is True

    def test_parse_clamps_threat_level(self):
        from helpstral.agent import parse_structured_assessment
        result = parse_structured_assessment('{"threat_level": 99, "status": "SAFE"}')
        assert result["threat_level"] == 10

    def test_parse_fixes_invalid_status(self):
        from helpstral.agent import parse_structured_assessment
        result = parse_structured_assessment('{"threat_level": 8, "status": "UNKNOWN"}')
        assert result["status"] == "DISTRESS"

    def test_parse_fixes_invalid_action(self):
        from helpstral.agent import parse_structured_assessment
        result = parse_structured_assessment('{"threat_level": 1, "action": "FIRE_MISSILES"}')
        assert result["action"] == "CONTINUE_MONITORING"

    def test_run_no_key(self):
        from helpstral.agent import run_helpstral_agent
        with patch("helpstral.agent.MISTRAL_API_KEY", ""):
            result = run_helpstral_agent("fakeimage")
            assert result["status"] == "SAFE"
            assert result["source"] == "no_key_fallback"
            assert "tool_calls_made" in result

    def test_tool_location_context(self):
        from helpstral.agent import tool_get_location_context
        result = json.loads(tool_get_location_context(48.86, 2.34))
        assert "neighborhood" in result
        assert "lighting_quality" in result
        assert "time_of_day" in result

    def test_tool_recent_assessments_empty(self):
        from helpstral.agent import tool_get_recent_assessments, set_shared_state
        set_shared_state([], {})
        result = json.loads(tool_get_recent_assessments())
        assert result["count"] == 0

    def test_tool_recent_assessments_with_history(self):
        from helpstral.agent import tool_get_recent_assessments, set_shared_state
        import time
        history = [
            {"threat_level": 1, "status": "SAFE", "pattern": "", "action": "", "timestamp": time.time()},
            {"threat_level": 5, "status": "CAUTION", "pattern": "test", "action": "", "timestamp": time.time()},
        ]
        set_shared_state(history, {})
        result = json.loads(tool_get_recent_assessments())
        assert result["count"] == 2

    def test_tool_escalate_emergency(self):
        from helpstral.agent import tool_escalate_emergency
        result = json.loads(tool_escalate_emergency(9, "Active threat", 48.86, 2.34))
        assert result["status"] == "escalated"
        assert "alert_id" in result

    def test_tool_definitions_valid(self):
        from helpstral.agent import TOOLS
        assert len(TOOLS) == 3
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {"get_location_context", "get_recent_assessments", "escalate_emergency"}
        for tool in TOOLS:
            assert tool["type"] == "function"
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]


# ── Flystral agent tests ─────────────────────────────────────────────────────

class TestFlystralAgent:
    def test_parse_valid_json(self):
        from flystral.agent import parse_structured_command
        raw = json.dumps({
            "scene_analysis": "Clear street", "threat_context": "SAFE",
            "command": "FOLLOW", "param": "0.6",
            "reasoning": "Normal.", "altitude_adjust": 0, "next_check": "Continue",
        })
        result = parse_structured_command(raw)
        assert result["command"] == "FOLLOW"
        assert result["param"] == "0.6"

    def test_parse_invalid_command_defaults(self):
        from flystral.agent import parse_structured_command
        result = parse_structured_command('{"command": "FIRE_LASER", "param": "100"}')
        assert result["command"] == "FOLLOW"
        assert result["param"] == "0.5"

    def test_parse_clamps_altitude(self):
        from flystral.agent import parse_structured_command
        result = parse_structured_command('{"command": "FOLLOW", "altitude_adjust": -50}')
        assert result["altitude_adjust"] == -20

    def test_parse_garbage_returns_default(self):
        from flystral.agent import parse_structured_command
        result = parse_structured_command("not valid json at all")
        assert result["command"] == "FOLLOW"
        assert result.get("parse_error") is True

    def test_run_no_key_safe(self):
        from flystral.agent import run_flystral_agent
        with patch("flystral.agent.MISTRAL_API_KEY", ""):
            result = run_flystral_agent("fakeimage")
            assert result["command"] == "FOLLOW"
            assert "tool_calls_made" in result

    def test_run_no_key_distress_adapts(self):
        from flystral.agent import run_flystral_agent
        with patch("flystral.agent.MISTRAL_API_KEY", ""):
            result = run_flystral_agent(
                "fakeimage",
                threat_assessment={"threat_level": 9, "status": "DISTRESS"},
            )
            assert result["command"] == "HOVER"
            assert result["altitude_adjust"] == -15

    def test_run_no_key_caution_adapts(self):
        from flystral.agent import run_flystral_agent
        with patch("flystral.agent.MISTRAL_API_KEY", ""):
            result = run_flystral_agent(
                "fakeimage",
                threat_assessment={"threat_level": 6, "status": "CAUTION"},
            )
            assert result["param"] == "0.3"
            assert result["altitude_adjust"] == -5

    def test_tool_telemetry(self):
        from flystral.agent import tool_get_drone_telemetry, set_shared_state
        set_shared_state({"alt": 25, "ground_speed": 5, "battery_pct": 80, "heading": 90}, {}, 0.5)
        result = json.loads(tool_get_drone_telemetry())
        assert result["altitude_m"] == 25
        assert result["battery_pct"] == 80

    def test_tool_threat_assessment(self):
        from flystral.agent import tool_get_threat_assessment, set_shared_state
        set_shared_state({}, {"threat_level": 7, "status": "CAUTION", "pattern": "test"}, None)
        result = json.loads(tool_get_threat_assessment())
        assert result["threat_level"] == 7
        assert result["status"] == "CAUTION"

    def test_tool_route_progress(self):
        from flystral.agent import tool_get_route_progress, set_shared_state
        set_shared_state({}, {}, 0.75)
        result = json.loads(tool_get_route_progress())
        assert result["progress_pct"] == 75

    def test_tool_definitions_valid(self):
        from flystral.agent import TOOLS
        assert len(TOOLS) == 3
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {"get_drone_telemetry", "get_threat_assessment", "get_route_progress"}


# ── Louise agent tests ────────────────────────────────────────────────────────

class TestLouiseAgent:
    def test_run_no_key(self):
        from louise.agent import run_louise_agent
        with patch("louise.agent.MISTRAL_API_KEY", ""):
            result = run_louise_agent("Is my route safe?")
            assert "response" in result
            assert result["source"] == "no_key_fallback"
            assert "tool_calls_made" in result

    def test_tool_route_safety(self):
        from louise.agent import tool_get_route_safety
        result = json.loads(tool_get_route_safety(48.86, 2.34, 48.87, 2.35))
        assert "overall_safety_score" in result
        assert 1 <= result["overall_safety_score"] <= 10

    def test_tool_escort_status_inactive(self):
        from louise.agent import tool_get_escort_status, set_shared_state
        set_shared_state({}, {})
        result = json.loads(tool_get_escort_status())
        assert result["active"] is False

    def test_tool_escort_status_active(self):
        from louise.agent import tool_get_escort_status, set_shared_state
        set_shared_state({"active": True, "phase": "escort", "battery_pct": 85, "threat_level": 1}, {})
        result = json.loads(tool_get_escort_status())
        assert result["active"] is True
        assert result["phase"] == "escort"

    def test_tool_area_info(self):
        from louise.agent import tool_get_area_info
        result = json.loads(tool_get_area_info(48.86, 2.34))
        assert "neighborhood" in result
        assert "safety_score" in result

    def test_tool_safety_tips(self):
        from louise.agent import tool_get_safety_tips
        result = json.loads(tool_get_safety_tips("walking alone in a park at night"))
        assert "tips" in result
        assert len(result["tips"]) > 0

    def test_tool_definitions_valid(self):
        from louise.agent import TOOLS
        assert len(TOOLS) == 5
        names = {t["function"]["name"] for t in TOOLS}
        assert names == {"get_route_safety", "get_escort_status", "get_area_info", "get_safety_tips", "escalate_emergency"}


# ── Agent loop integration tests ─────────────────────────────────────────────

class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_agent_loop_no_key(self):
        with patch("helpstral.agent.MISTRAL_API_KEY", ""), \
             patch("flystral.agent.MISTRAL_API_KEY", ""):
            import server
            server._assessment_history.clear()
            server._latest_telemetry = {}
            server._latest_user_position = {}
            server._latest_helpstral = dict(server.HELPSTRAL_DEFAULT)
            server._latest_flystral = dict(server.FLYSTRAL_DEFAULT)

            result = await server.agent_loop("fakebase64image")
            assert "helpstral" in result
            assert "flystral" in result
            assert result["helpstral"]["status"] == "SAFE"
            assert result["flystral"]["command"] == "FOLLOW"
            assert "tool_calls_made" in result["helpstral"]

    @pytest.mark.asyncio
    async def test_agent_loop_updates_history(self):
        with patch("helpstral.agent.MISTRAL_API_KEY", ""), \
             patch("flystral.agent.MISTRAL_API_KEY", ""):
            import server
            server._assessment_history.clear()
            await server.agent_loop("fakebase64image")
            assert len(server._assessment_history) == 1

    @pytest.mark.asyncio
    async def test_sync_shared_state(self):
        import server
        server._latest_user_position = {"lat": 48.86, "lng": 2.34}
        server._latest_telemetry = {"alt": 25, "battery_pct": 80}
        server._sync_shared_state()
        from flystral.agent import _telemetry_ref
        assert _telemetry_ref.get("alt") == 25


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestAgentEndpoints:
    @pytest.mark.asyncio
    async def test_helpstral_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        from server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/helpstral", json={"image": "fakebase64"})
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert "threat_level" in data or "source" in data

    @pytest.mark.asyncio
    async def test_flystral_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        from server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/flystral", json={"image": "fakebase64"})
            assert resp.status_code == 200
            data = resp.json()
            assert "command" in data

    @pytest.mark.asyncio
    async def test_agent_loop_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        from server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/agent-loop", json={"image": "fakebase64"})
            assert resp.status_code == 200
            data = resp.json()
            assert "helpstral" in data
            assert "flystral" in data

    @pytest.mark.asyncio
    async def test_louise_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        from server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/louise", json={"message": "Is my area safe?"})
            assert resp.status_code == 200
            data = resp.json()
            assert "response" in data
            assert "tool_calls_made" in data

    @pytest.mark.asyncio
    async def test_agent_status_endpoint(self):
        from httpx import AsyncClient, ASGITransport
        from server import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/agent-status")
            assert resp.status_code == 200
            data = resp.json()
            assert "loop_active" in data
            assert "mission_active" in data
            assert "helpstral" in data
            assert "flystral" in data
