"""Tests for the multi-agent system: Helpstral agent, Flystral agent, agent loop."""

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
            "threat_level": 3,
            "status": "SAFE",
            "observations": ["well-lit street", "no pedestrians"],
            "pattern": "Consistent safe",
            "reasoning": "Normal conditions.",
            "action": "CONTINUE_MONITORING",
        })
        result = parse_structured_assessment(raw)
        assert result["threat_level"] == 3
        assert result["status"] == "SAFE"
        assert len(result["observations"]) == 2
        assert result["action"] == "CONTINUE_MONITORING"

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
        assert result["status"] == "CAUTION"

    def test_parse_garbage_returns_default(self):
        from helpstral.agent import parse_structured_assessment, DEFAULT_ASSESSMENT
        result = parse_structured_assessment("just some random text no json here")
        assert result["status"] == "SAFE"
        assert result["threat_level"] == 1
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

    def test_location_context_returns_dict(self):
        from helpstral.agent import get_location_context
        ctx = get_location_context(48.86, 2.34)
        assert "area_type" in ctx
        assert "lighting_estimate" in ctx
        assert "time_of_day" in ctx

    def test_format_context_no_history(self):
        from helpstral.agent import format_context
        result = format_context([], None, None)
        assert "first frame" in result.lower()

    def test_format_context_with_history(self):
        from helpstral.agent import format_context
        history = [{"status": "SAFE", "threat_level": 1}, {"status": "CAUTION", "threat_level": 5}]
        result = format_context(history, None, 0.5)
        assert "50%" in result
        assert "SAFE" in result


# ── Flystral agent tests ─────────────────────────────────────────────────────

class TestFlystralAgent:
    def test_parse_valid_json(self):
        from flystral.agent import parse_structured_command
        raw = json.dumps({
            "scene_analysis": "Clear street",
            "threat_context": "SAFE",
            "command": "FOLLOW",
            "param": "0.6",
            "reasoning": "Normal conditions.",
            "altitude_adjust": 0,
            "next_check": "Continue",
        })
        result = parse_structured_command(raw)
        assert result["command"] == "FOLLOW"
        assert result["param"] == "0.6"
        assert result["altitude_adjust"] == 0

    def test_parse_invalid_command_defaults(self):
        from flystral.agent import parse_structured_command
        raw = json.dumps({"command": "FIRE_LASER", "param": "100"})
        result = parse_structured_command(raw)
        assert result["command"] == "FOLLOW"
        assert result["param"] == "0.5"

    def test_parse_clamps_altitude(self):
        from flystral.agent import parse_structured_command
        raw = json.dumps({"command": "FOLLOW", "altitude_adjust": -50})
        result = parse_structured_command(raw)
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
            assert result["param"] == "0.5"

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

    def test_telemetry_context_low_battery(self):
        from flystral.agent import format_telemetry_context
        result = format_telemetry_context(
            telemetry={"alt": 25, "ground_speed": 4, "battery_pct": 15, "heading": 90},
        )
        assert "WARNING" in result
        assert "battery" in result.lower()


# ── Agent loop integration tests ─────────────────────────────────────────────

class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_agent_loop_no_key(self):
        """Agent loop works with no API key (fallback mode)."""
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

    @pytest.mark.asyncio
    async def test_agent_loop_updates_history(self):
        """Agent loop appends to assessment history."""
        with patch("helpstral.agent.MISTRAL_API_KEY", ""), \
             patch("flystral.agent.MISTRAL_API_KEY", ""):
            import server
            server._assessment_history.clear()
            initial_len = len(server._assessment_history)
            await server.agent_loop("fakebase64image")
            assert len(server._assessment_history) == initial_len + 1

    @pytest.mark.asyncio
    async def test_agent_loop_auto_escalation(self):
        """Agent loop auto-escalates after 3 consecutive high-threat assessments."""
        with patch("helpstral.agent.MISTRAL_API_KEY", ""), \
             patch("flystral.agent.MISTRAL_API_KEY", ""):
            import server
            server._assessment_history.clear()
            for _ in range(2):
                server._assessment_history.append({"threat_level": 7, "status": "CAUTION"})

            mock_helpstral = {
                "threat_level": 7, "status": "CAUTION",
                "observations": ["test"], "pattern": "test",
                "reasoning": "test", "action": "ALERT_USER",
            }
            with patch("server.run_helpstral_agent", return_value=mock_helpstral), \
                 patch("server.run_flystral_agent", return_value=dict(server.FLYSTRAL_DEFAULT)):
                broadcast_calls = []
                original_broadcast = server.manager.broadcast
                async def capture_broadcast(msg):
                    broadcast_calls.append(msg)
                    return await original_broadcast(msg)
                server.manager.broadcast = capture_broadcast

                await server.agent_loop("fakebase64image")

                emergency_msgs = [m for m in broadcast_calls if m.get("type") == "emergency"]
                assert len(emergency_msgs) >= 1
                assert emergency_msgs[0]["origin"] == "helpstral_auto_escalation"

                server.manager.broadcast = original_broadcast


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
            assert data["helpstral"]["status"] in ("SAFE", "CAUTION", "DISTRESS")
            assert data["flystral"]["command"] in ("FOLLOW", "AVOID_LEFT", "AVOID_RIGHT", "CLIMB", "DESCEND", "HOVER", "REPLAN")
