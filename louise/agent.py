"""
Ask Louise — user-facing conversational AI agent with Mistral function calling.

Users can ask Louise about their route safety, ETA, area information,
or request help. Louise uses tools to query real system state.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MISTRAL_API_KEY, MISTRAL_GENERAL_MODEL, DRONE_HUB

SYSTEM_PROMPT = (
    "You are Louise, a personal safety AI assistant built into a drone escort app. "
    "You help users feel safe walking alone at night in Paris.\n\n"
    "You can use tools to answer questions:\n"
    "- get_route_safety: analyze how safe a walking route is\n"
    "- get_escort_status: check the current drone escort status\n"
    "- get_area_info: get information about a specific area\n"
    "- get_safety_tips: get contextual safety advice\n\n"
    "Be concise, warm, and reassuring. Never be alarmist without reason. "
    "If the user seems distressed, take it seriously and offer concrete help. "
    "Keep responses under 3 sentences unless the user asks for detail."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_route_safety",
            "description": "Analyze safety of a walking route between two points. Returns lighting quality, foot traffic level, known incident areas, and an overall safety score.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_lat": {"type": "number", "description": "Starting latitude"},
                    "from_lng": {"type": "number", "description": "Starting longitude"},
                    "to_lat": {"type": "number", "description": "Destination latitude"},
                    "to_lng": {"type": "number", "description": "Destination longitude"},
                },
                "required": ["from_lat", "from_lng", "to_lat", "to_lng"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_escort_status",
            "description": "Get the current status of the user's drone escort: whether a drone is active, its distance, battery level, and current phase (approaching, escorting, returning).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_area_info",
            "description": "Get information about a specific area: neighborhood name, area type, typical foot traffic, lighting quality, and safety notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "Latitude"},
                    "lng": {"type": "number", "description": "Longitude"},
                },
                "required": ["lat", "lng"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_safety_tips",
            "description": "Get contextual safety tips based on time of day, area type, and weather. Provides practical advice for walking safely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "context": {"type": "string", "description": "Brief context like 'walking home late at night' or 'crossing park'"},
                },
                "required": ["context"],
            },
        },
    },
]

# ── Shared state (set by server.py) ──────────────────────────────────────────

_escort_state: dict = {}
_user_position: dict = {}


def set_shared_state(escort: dict, user_pos: dict):
    global _escort_state, _user_position
    _escort_state = escort
    _user_position = user_pos


# ── Tool implementations ─────────────────────────────────────────────────────

def tool_get_route_safety(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> str:
    hour = datetime.now().hour
    is_night = hour < 6 or hour >= 20

    central = (48.85 <= from_lat <= 48.87) and (48.85 <= to_lat <= 48.87)
    score = 8 if central else 6
    if is_night:
        score -= 2
    score = max(1, min(10, score))

    return json.dumps({
        "safety_score": score,
        "lighting": "good" if central else "moderate",
        "foot_traffic": "low" if is_night else "moderate",
        "estimated_walk_minutes": int(abs(to_lat - from_lat) * 111000 / 80),
        "recommendation": "Route looks safe" if score >= 6 else "Consider requesting a drone escort",
    })


def tool_get_escort_status() -> str:
    if not _escort_state:
        return json.dumps({"active": False, "message": "No active escort. Request one from the main screen."})

    return json.dumps({
        "active": _escort_state.get("active", False),
        "phase": _escort_state.get("phase", "unknown"),
        "battery_pct": _escort_state.get("battery_pct", 100),
        "distance_to_user_m": _escort_state.get("distance_to_user", 0),
        "threat_level": _escort_state.get("threat_level", 1),
    })


def tool_get_area_info(lat: float, lng: float) -> str:
    if 48.855 <= lat <= 48.865 and 2.33 <= lng <= 2.35:
        name, area_type = "Louvre / Tuileries", "Major landmark area"
        traffic, lighting = "high", "excellent"
        notes = "Tourist area, well-patrolled, many cameras"
    elif 48.845 <= lat <= 48.855 and 2.34 <= lng <= 2.36:
        name, area_type = "Saint-Germain-des-Pres", "Historic commercial district"
        traffic, lighting = "moderate", "good"
        notes = "Lively area with restaurants and shops"
    elif 48.87 <= lat <= 48.88:
        name, area_type = "Montmartre", "Residential / tourist"
        traffic, lighting = "moderate", "moderate"
        notes = "Hilly area, some quieter side streets"
    else:
        name, area_type = "Paris residential", "Urban residential"
        traffic, lighting = "low", "moderate"
        notes = "Standard residential area"

    return json.dumps({
        "neighborhood": name, "area_type": area_type,
        "typical_foot_traffic": traffic, "lighting_quality": lighting,
        "safety_notes": notes,
    })


def tool_get_safety_tips(context: str) -> str:
    hour = datetime.now().hour
    is_night = hour < 6 or hour >= 20

    tips = [
        "Stay on well-lit main roads where possible",
        "Keep your phone charged and easily accessible",
        "Share your live location with a trusted contact",
    ]
    if is_night:
        tips.extend([
            "Avoid parks and unlit side streets after dark",
            "Walk facing oncoming traffic so you can see approaching vehicles",
            "If you feel unsafe, enter any open shop, restaurant, or hotel lobby",
        ])
    if "park" in context.lower():
        tips.append("Parks can be poorly lit at night — stick to main paths with lamp posts")
    if "alone" in context.lower():
        tips.append("Consider requesting a Louise drone escort for added security")

    return json.dumps({"tips": tips[:5], "time_of_day": "night" if is_night else "day"})


TOOL_DISPATCH = {
    "get_route_safety": lambda args: tool_get_route_safety(**args),
    "get_escort_status": lambda args: tool_get_escort_status(),
    "get_area_info": lambda args: tool_get_area_info(args.get("lat", 0), args.get("lng", 0)),
    "get_safety_tips": lambda args: tool_get_safety_tips(args.get("context", "")),
}


# ── Agent execution ──────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 3


def run_louise_agent(
    user_message: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Run Ask Louise: the model can call tools to query route safety,
    escort status, area info, etc. before responding to the user.
    """
    if not MISTRAL_API_KEY:
        return {
            "response": "I'm Louise, your safety assistant. I'm currently in offline mode, "
                        "but I can still help. What do you need?",
            "tool_calls_made": [],
            "source": "no_key_fallback",
        }

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history[-10:])
    messages.append({"role": "user", "content": user_message})

    tool_calls_made = []

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        for _round in range(MAX_TOOL_ROUNDS + 1):
            response = client.chat.complete(
                model=MISTRAL_GENERAL_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=300,
                temperature=0.3,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                return {
                    "response": (msg.content or "").strip(),
                    "tool_calls_made": tool_calls_made,
                }

            messages.append(msg)

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_calls_made.append({"tool": fn_name, "args": fn_args})

                executor = TOOL_DISPATCH.get(fn_name)
                fn_result = executor(fn_args) if executor else json.dumps({"error": f"Unknown tool: {fn_name}"})

                messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": fn_result,
                    "tool_call_id": tc.id,
                })

        return {
            "response": (msg.content or "I'm here to help. Could you rephrase?").strip(),
            "tool_calls_made": tool_calls_made,
        }

    except Exception as e:
        return {
            "response": "I'm having trouble connecting right now. If you need immediate help, tap the emergency button.",
            "error": str(e),
            "tool_calls_made": tool_calls_made,
        }
