"""
Helpstral Agent — agentic safety monitor with Mistral function calling.

The model decides which tools to call (get_location_context, get_recent_assessments,
escalate_emergency), receives results, reasons over them, and produces a structured
threat assessment. This is real tool use, not context stuffing.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HELPSTRAL_ENDPOINT

SYSTEM_PROMPT = (
    "You are Helpstral, a safety AI monitoring a drone escort camera feed protecting a person "
    "walking alone at night.\n\n"
    "PROCESS — follow these steps:\n"
    "1. Call get_location_context to query real streetlight density, lit road data, and POIs from OpenStreetMap\n"
    "2. Call get_recent_assessments to review your sliding memory window for temporal patterns\n"
    "3. Analyze the image: identify people, their distance/trajectory relative to the user, "
    "lighting conditions visible in frame, obstacles, and environmental threats\n"
    "4. Cross-reference what you see with what the location data tells you — if OSM says "
    "4 streetlights but the image looks dark, the lights may be broken\n"
    "5. If threat_level >= 8, call escalate_emergency before responding\n\n"
    "BODY DETECTION — critical for operator alerts:\n"
    "- Count the number of people visible in the frame (people_count)\n"
    "- Determine if the escorted user appears to be walking (user_moving: true/false)\n"
    "- If another person is within ~3 metres of the user, set proximity_alert: true\n"
    "- These fields trigger automatic operator review in mission control\n\n"
    "MULTI-FRAME REASONING — you are not classifying a single image. You are tracking a situation "
    "over time. When reviewing recent assessments, look for:\n"
    "- Is a person getting closer frame-over-frame? (closing distance = potential follower)\n"
    "- Has the lighting environment changed? (user entering darker area)\n"
    "- Has the user's pace changed? (running = fleeing, stopped = potential problem)\n"
    "- Is the same individual appearing across multiple frames? (persistent presence)\n\n"
    "Final answer MUST be a JSON object:\n"
    "- threat_level: integer 1-10 (evidence-based, not just vibes)\n"
    "- status: SAFE, CAUTION, or DISTRESS\n"
    "- people_count: integer — number of people visible in frame\n"
    "- user_moving: boolean — whether the escorted user appears to be walking\n"
    "- proximity_alert: boolean — whether another person is within ~3m of the user\n"
    "- observations: array of 2-4 specific strings (what you actually see, not generic)\n"
    "- pattern: string describing temporal patterns from memory (or 'First assessment' if no history)\n"
    "- reasoning: 2-3 sentences connecting image evidence + location data + temporal patterns\n"
    "- action: CONTINUE_MONITORING, INCREASE_SCAN_RATE, ALERT_USER, ACTIVATE_SPOTLIGHT, or EMERGENCY_HOVER"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_location_context",
            "description": "Query real OpenStreetMap data for the user's position: streetlight count within 300m, lit/unlit road ratio, nearby POIs (restaurants, shops, emergency services), reverse-geocoded neighborhood name, and a composite safety score. Use this to understand the real environment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Latitude of the user"},
                    "lng": {"type": "number", "description": "Longitude of the user"},
                },
                "required": ["lat", "lng"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_assessments",
            "description": "Retrieve the last 3-5 threat assessments from the sliding window memory. Use this to detect patterns like someone following across multiple frames.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_emergency",
            "description": "Trigger an emergency alert to mission control. Only call when you detect real danger (threat_level >= 8). This notifies the operator and can dispatch help.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Threat level 1-10"},
                    "reasoning": {"type": "string", "description": "Why this is an emergency"},
                    "lat": {"type": "number", "description": "Latitude where threat detected"},
                    "lng": {"type": "number", "description": "Longitude where threat detected"},
                },
                "required": ["level", "reasoning"],
            },
        },
    },
]

VALID_STATUSES = {"SAFE", "CAUTION", "DISTRESS"}
VALID_ACTIONS = {
    "CONTINUE_MONITORING", "INCREASE_SCAN_RATE", "ALERT_USER",
    "ACTIVATE_SPOTLIGHT", "EMERGENCY_HOVER",
}

DEFAULT_ASSESSMENT = {
    "threat_level": 1,
    "status": "SAFE",
    "observations": ["No image available or analysis failed"],
    "pattern": "No pattern",
    "reasoning": "Default safe assessment — no image data or API unavailable.",
    "action": "CONTINUE_MONITORING",
}

# ── Tool implementations ─────────────────────────────────────────────────────

_assessment_history_ref: list[dict] = []
_escalation_log: list[dict] = []
_user_position_ref: dict = {}
_escalation_callback = None


def set_shared_state(history: list[dict], user_pos: dict, escalation_callback=None):
    """Called by server.py to share live state with the agent."""
    global _assessment_history_ref, _user_position_ref, _escalation_callback
    _assessment_history_ref = history
    _user_position_ref = user_pos
    if escalation_callback is not None:
        _escalation_callback = escalation_callback


def tool_get_location_context(lat: float, lng: float) -> str:
    """Query real OSM data: streetlight count, lit road ratio, POIs, neighborhood name."""
    try:
        from geo_intel import compute_area_safety_score
        data = compute_area_safety_score(lat, lng)
        return json.dumps({
            "neighborhood": data.get("neighborhood", "Unknown"),
            "road": data.get("road", "Unknown"),
            "safety_score": data.get("safety_score", 5),
            "lighting_quality": data.get("lighting_quality", "unknown"),
            "streetlights_within_300m": data.get("streetlights_nearby", 0),
            "lit_roads": data.get("lit_roads", {}),
            "foot_traffic": data.get("foot_traffic_level", "unknown"),
            "pois_nearby": data.get("pois_nearby", 0),
            "emergency_services_nearby": data.get("emergency_services_nearby", 0),
            "time_of_day": data.get("time_of_day", "unknown"),
            "scoring": data.get("scoring_breakdown", {}),
        })
    except Exception as e:
        hour = datetime.now().hour
        return json.dumps({
            "neighborhood": "Unknown", "safety_score": 5,
            "lighting_quality": "unknown", "time_of_day": "night" if hour < 6 or hour >= 20 else "day",
            "error": str(e),
        })


def tool_get_recent_assessments() -> str:
    recent = _assessment_history_ref[-5:] if _assessment_history_ref else []
    summary = []
    now = time.time()
    for a in recent:
        ts = a.get("timestamp")
        summary.append({
            "threat_level": a.get("threat_level", 1),
            "status": a.get("status", "SAFE"),
            "pattern": a.get("pattern", ""),
            "action": a.get("action", ""),
            "age_seconds": int(now - ts) if ts else 0,
        })
    return json.dumps({"count": len(summary), "assessments": summary})


def tool_escalate_emergency(level: int, reasoning: str, lat: float = 0, lng: float = 0) -> str:
    entry = {
        "level": level, "reasoning": reasoning,
        "lat": lat, "lng": lng, "timestamp": time.time(),
        "origin": "helpstral",
    }
    _escalation_log.append(entry)
    if _escalation_callback:
        _escalation_callback(entry)
    return json.dumps({"status": "escalated", "alert_id": len(_escalation_log)})


TOOL_DISPATCH = {
    "get_location_context": lambda args: tool_get_location_context(args.get("lat", 0), args.get("lng", 0)),
    "get_recent_assessments": lambda args: tool_get_recent_assessments(),
    "escalate_emergency": lambda args: tool_escalate_emergency(**args),
}


def get_location_context(lat: float, lng: float) -> dict:
    """Public helper — returns real OSM-based area context."""
    return json.loads(tool_get_location_context(lat, lng))


# ── JSON parsing ──────────────────────────────────────────────────────────────

def parse_structured_assessment(raw: str) -> dict:
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
                return {**DEFAULT_ASSESSMENT, "raw": raw, "parse_error": True}
        else:
            return {**DEFAULT_ASSESSMENT, "raw": raw, "parse_error": True}

    result.setdefault("threat_level", 1)
    result.setdefault("status", "SAFE")
    result.setdefault("people_count", 1)
    result.setdefault("user_moving", True)
    result.setdefault("proximity_alert", False)
    result.setdefault("observations", [])
    result.setdefault("pattern", "No pattern")
    result.setdefault("reasoning", "")
    result.setdefault("action", "CONTINUE_MONITORING")

    if result["status"] not in VALID_STATUSES:
        result["status"] = "SAFE" if result["threat_level"] < 5 else "CAUTION" if result["threat_level"] < 8 else "DISTRESS"
    if result["action"] not in VALID_ACTIONS:
        result["action"] = "CONTINUE_MONITORING"
    result["threat_level"] = max(1, min(10, int(result["threat_level"])))

    return result


# ── Remote endpoint (fine-tuned Helpstral served via Colab/ngrok) ─────────────

def _run_remote_endpoint(image_b64: str) -> dict | None:
    """Call the fine-tuned Helpstral endpoint if configured. Returns None on failure."""
    if not HELPSTRAL_ENDPOINT:
        return None
    try:
        import requests
        resp = requests.post(
            f"{HELPSTRAL_ENDPOINT.rstrip('/')}/predict",
            json={"image": image_b64},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result = parse_structured_assessment(json.dumps(data))
        result["timestamp"] = time.time()
        result["model"] = data.get("model", "helpstral-finetuned")
        result["source"] = "finetuned"
        result["tool_calls_made"] = []
        return result
    except Exception as e:
        print(f"[Helpstral] Endpoint failed, falling back to Mistral API: {e}")
        return None


# ── Agent execution with tool loop ───────────────────────────────────────────

MAX_TOOL_ROUNDS = 3


def run_helpstral_agent(
    image_b64: str,
    recent_assessments: list[dict] | None = None,
    location: dict | None = None,
    route_progress: float | None = None,
) -> dict:
    """Run Helpstral via fine-tuned endpoint only (BenBarr/helpstral)."""
    if not HELPSTRAL_ENDPOINT:
        return {**DEFAULT_ASSESSMENT, "source": "endpoint_required", "tool_calls_made": [],
                "reasoning": "HELPSTRAL_ENDPOINT not set. Run helpstral/serve_colab.ipynb and set in .env."}

    result = _run_remote_endpoint(image_b64)
    if result:
        return result

    return {**DEFAULT_ASSESSMENT, "source": "endpoint_error", "tool_calls_made": [],
            "reasoning": "Helpstral endpoint unavailable."}
