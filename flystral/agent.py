"""
Flystral Agent — structured flight controller with threat awareness and telemetry.

Produces structured JSON flight commands that adapt based on Helpstral's threat assessment.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FLYSTRAL_MODEL_ID, MISTRAL_API_KEY
from flystral.command_parser import VALID_COMMANDS

SYSTEM_PROMPT = (
    "You are Flystral, a drone autopilot AI for a safety escort drone. "
    "Analyze the drone camera image with the provided telemetry and threat context.\n\n"
    "You MUST respond with ONLY a valid JSON object (no markdown, no explanation) with these fields:\n"
    "- scene_analysis: 1 sentence describing what you see in the image\n"
    "- threat_context: 1 sentence about the current threat situation from Helpstral\n"
    "- command: one of FOLLOW, AVOID_LEFT, AVOID_RIGHT, CLIMB, DESCEND, HOVER, REPLAN\n"
    "- param: string number (speed 0.1-1.0 for FOLLOW, metres for AVOID/CLIMB/DESCEND, seconds for HOVER)\n"
    "- reasoning: 1-2 sentence explanation of why this command\n"
    "- altitude_adjust: integer metres to adjust altitude (-20 to +20, 0 if no change)\n"
    "- next_check: 1 sentence about what to monitor next\n\n"
    "CRITICAL RULES:\n"
    "- If threat_level >= 6: reduce speed (param 0.2-0.4), decrease altitude to stay closer\n"
    "- If threat_level >= 8 (DISTRESS): HOVER directly above user, altitude_adjust to -15\n"
    "- If threat_level <= 3: normal FOLLOW at 0.5-0.8 speed\n"
    "- Always consider battery — if below 20%, prioritize return\n\n"
    "Example output:\n"
    '{"scene_analysis": "Clear urban street, good visibility", "threat_context": "SAFE — no threats", '
    '"command": "FOLLOW", "param": "0.6", "reasoning": "Normal conditions, maintaining standard escort.", '
    '"altitude_adjust": 0, "next_check": "Continue routine monitoring"}'
)

DEFAULT_RESULT = {
    "scene_analysis": "No image available",
    "threat_context": "Unknown — using default",
    "command": "FOLLOW",
    "param": "0.5",
    "reasoning": "Default follow — no image data or API unavailable.",
    "altitude_adjust": 0,
    "next_check": "Await next frame",
}


def format_telemetry_context(
    threat_assessment: dict | None = None,
    telemetry: dict | None = None,
    route_progress: float | None = None,
) -> str:
    """Build the text context that accompanies the image for Flystral."""
    parts = []

    tel = telemetry or {}
    parts.append(
        f"Telemetry: alt={tel.get('alt', '?')}m, speed={tel.get('ground_speed', '?')}m/s, "
        f"battery={tel.get('battery_pct', '?')}%, heading={tel.get('heading', '?')}."
    )

    if threat_assessment:
        tl = threat_assessment.get("threat_level", 1)
        status = threat_assessment.get("status", "SAFE")
        pattern = threat_assessment.get("pattern", "No pattern")
        parts.append(
            f'Helpstral: {{"threat_level": {tl}, "status": "{status}", "pattern": "{pattern}"}}.'
        )
    else:
        parts.append("Helpstral: No assessment available.")

    if route_progress is not None:
        parts.append(f"Route: {int(route_progress * 100)}% complete.")

    if tel.get("battery_pct") is not None and isinstance(tel["battery_pct"], (int, float)) and tel["battery_pct"] <= 20:
        parts.append("WARNING: Low battery — consider return.")

    return " ".join(parts)


def parse_structured_command(raw: str) -> dict:
    """Parse model output as JSON. Falls back to default if parsing fails."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(l for l in lines if not l.strip().startswith("```"))

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start:end])
            except json.JSONDecodeError:
                return {**DEFAULT_RESULT, "raw": raw, "parse_error": True}
        else:
            return {**DEFAULT_RESULT, "raw": raw, "parse_error": True}

    result.setdefault("scene_analysis", "")
    result.setdefault("threat_context", "")
    result.setdefault("command", "FOLLOW")
    result.setdefault("param", "0.5")
    result.setdefault("reasoning", "")
    result.setdefault("altitude_adjust", 0)
    result.setdefault("next_check", "")

    cmd = str(result["command"]).upper().strip()
    if cmd not in VALID_COMMANDS:
        cmd = "FOLLOW"
        result["param"] = "0.5"
    result["command"] = cmd

    try:
        result["altitude_adjust"] = max(-20, min(20, int(result["altitude_adjust"])))
    except (ValueError, TypeError):
        result["altitude_adjust"] = 0

    return result


def run_flystral_agent(
    image_b64: str,
    threat_assessment: dict | None = None,
    telemetry: dict | None = None,
    route_progress: float | None = None,
) -> dict:
    """
    Run the Flystral agent: image + threat + telemetry → structured flight command.
    Returns a dict with command, param, reasoning, altitude_adjust, etc.
    """
    if not MISTRAL_API_KEY:
        result = dict(DEFAULT_RESULT)
        if threat_assessment and threat_assessment.get("threat_level", 1) >= 8:
            result["command"] = "HOVER"
            result["param"] = "10"
            result["altitude_adjust"] = -15
            result["reasoning"] = "DISTRESS detected — hovering above user (no API key, using fallback)."
        elif threat_assessment and threat_assessment.get("threat_level", 1) >= 5:
            result["param"] = "0.3"
            result["altitude_adjust"] = -5
            result["reasoning"] = "Caution — slowing and lowering altitude (no API key, using fallback)."
        result["source"] = "no_key_fallback"
        return result

    context_text = format_telemetry_context(threat_assessment, telemetry, route_progress)

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        response = client.chat.complete(
            model=FLYSTRAL_MODEL_ID,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": f"Context: {context_text}"},
                    ],
                },
            ],
            max_tokens=500,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        result = parse_structured_command(raw)
        result["timestamp"] = time.time()
        return result

    except Exception as e:
        return {**DEFAULT_RESULT, "error": str(e), "timestamp": time.time()}
