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
from config import HELPSTRAL_MODEL_ID, MISTRAL_API_KEY, MISTRAL_VISION_MODEL

SYSTEM_PROMPT = (
    "You are Helpstral, a safety AI monitoring a drone escort camera feed protecting a person "
    "walking alone at night.\n\n"
    "You have tools available. Use them to gather context before making your assessment:\n"
    "- get_location_context: understand the area type and lighting\n"
    "- get_recent_assessments: check your previous assessments for patterns\n"
    "- escalate_emergency: trigger an alert if you detect real danger (threat_level >= 8)\n\n"
    "After using tools (or if none are needed), produce your final answer as a JSON object with:\n"
    "- threat_level: integer 1-10\n"
    "- status: SAFE, CAUTION, or DISTRESS\n"
    "- observations: array of 2-4 strings describing what you see\n"
    "- pattern: string describing patterns across recent assessments\n"
    "- reasoning: 1-2 sentence explanation\n"
    "- action: one of CONTINUE_MONITORING, INCREASE_SCAN_RATE, ALERT_USER, ACTIVATE_SPOTLIGHT, EMERGENCY_HOVER"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_location_context",
            "description": "Get area type, lighting estimate, and time of day for the user's current GPS position. Call this to understand the environment.",
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


def set_shared_state(history: list[dict], user_pos: dict):
    """Called by server.py to share live state with the agent."""
    global _assessment_history_ref, _user_position_ref
    _assessment_history_ref = history
    _user_position_ref = user_pos


def tool_get_location_context(lat: float, lng: float) -> str:
    hour = datetime.now().hour
    time_of_day = "night" if hour < 6 or hour >= 20 else "evening" if hour >= 17 else "day"
    lighting = "low" if time_of_day == "night" else "moderate" if time_of_day == "evening" else "good"

    if 48.85 <= lat <= 48.87 and 2.33 <= lng <= 2.35:
        area_type = "central Paris — tourist area, well-lit main roads"
    elif 48.87 <= lat <= 48.89:
        area_type = "northern Paris — mixed residential and commercial"
    elif 48.83 <= lat <= 48.85:
        area_type = "southern Paris — quiet residential"
    else:
        area_type = "urban residential area"

    return json.dumps({
        "area_type": area_type, "lighting_estimate": lighting,
        "time_of_day": time_of_day, "hour": hour,
    })


def tool_get_recent_assessments() -> str:
    recent = _assessment_history_ref[-5:] if _assessment_history_ref else []
    summary = []
    for a in recent:
        summary.append({
            "threat_level": a.get("threat_level", 1),
            "status": a.get("status", "SAFE"),
            "pattern": a.get("pattern", ""),
            "action": a.get("action", ""),
            "age_seconds": int(time.time() - a.get("timestamp", time.time())),
        })
    return json.dumps({"count": len(summary), "assessments": summary})


def tool_escalate_emergency(level: int, reasoning: str, lat: float = 0, lng: float = 0) -> str:
    entry = {
        "level": level, "reasoning": reasoning,
        "lat": lat, "lng": lng, "timestamp": time.time(),
    }
    _escalation_log.append(entry)
    return json.dumps({"status": "escalated", "alert_id": len(_escalation_log)})


TOOL_DISPATCH = {
    "get_location_context": lambda args: tool_get_location_context(args.get("lat", 0), args.get("lng", 0)),
    "get_recent_assessments": lambda args: tool_get_recent_assessments(),
    "escalate_emergency": lambda args: tool_escalate_emergency(**args),
}


def get_location_context(lat: float, lng: float) -> dict:
    """Public helper for server.py backwards compat."""
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


# ── Agent execution with tool loop ───────────────────────────────────────────

MAX_TOOL_ROUNDS = 3


def run_helpstral_agent(
    image_b64: str,
    recent_assessments: list[dict] | None = None,
    location: dict | None = None,
    route_progress: float | None = None,
) -> dict:
    """
    Run Helpstral as a real agent: the model decides which tools to call,
    receives results, and reasons over them before producing its assessment.
    """
    if not MISTRAL_API_KEY:
        return {**DEFAULT_ASSESSMENT, "source": "no_key_fallback", "tool_calls_made": []}

    if recent_assessments is not None:
        global _assessment_history_ref
        _assessment_history_ref = recent_assessments

    user_lat = _user_position_ref.get("lat", 48.86)
    user_lng = _user_position_ref.get("lng", 2.34)

    progress_note = ""
    if route_progress is not None:
        progress_note = f" Escort is {int(route_progress * 100)}% complete."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": (
                    f"Analyze this frame. The user is at lat={user_lat}, lng={user_lng}.{progress_note} "
                    "Use your tools to gather context, then provide your structured threat assessment as JSON."
                )},
            ],
        },
    ]

    tool_calls_made = []

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        model = HELPSTRAL_MODEL_ID or MISTRAL_VISION_MODEL

        for _round in range(MAX_TOOL_ROUNDS + 1):
            response = client.chat.complete(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=600,
                temperature=0.1,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                raw = (msg.content or "").strip()
                result = parse_structured_assessment(raw)
                result["timestamp"] = time.time()
                result["tool_calls_made"] = tool_calls_made
                return result

            messages.append(msg)

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_calls_made.append({"tool": fn_name, "args": fn_args})

                executor = TOOL_DISPATCH.get(fn_name)
                if executor:
                    fn_result = executor(fn_args)
                else:
                    fn_result = json.dumps({"error": f"Unknown tool: {fn_name}"})

                messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": fn_result,
                    "tool_call_id": tc.id,
                })

        raw = (msg.content or "").strip() if msg else ""
        result = parse_structured_assessment(raw)
        result["timestamp"] = time.time()
        result["tool_calls_made"] = tool_calls_made
        return result

    except Exception as e:
        return {**DEFAULT_ASSESSMENT, "error": str(e), "timestamp": time.time(), "tool_calls_made": tool_calls_made}
