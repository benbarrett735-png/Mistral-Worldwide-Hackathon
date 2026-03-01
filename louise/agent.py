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
from config import MISTRAL_API_KEY, MISTRAL_FAST_MODEL, DRONE_HUB, CITY_HUBS, DEFAULT_CITY

_SYSTEM_PROMPT_TEMPLATE = (
    "You are Louise, a personal safety AI assistant built into a drone escort app. "
    "You help users feel safe walking alone at night in {city_name}.\n\n"
    "You can use tools to answer questions:\n"
    "- get_route_safety: analyze how safe a walking route is\n"
    "- get_escort_status: check the current drone escort status\n"
    "- get_area_info: get information about a specific area\n"
    "- get_safety_tips: get contextual safety advice\n\n"
    "Be concise, warm, and reassuring. Never be alarmist without reason. "
    "If the user seems distressed, take it seriously and offer concrete help. "
    "Keep responses under 3 sentences unless the user asks for detail."
)


def _get_system_prompt() -> str:
    city_key = _current_city or DEFAULT_CITY
    city_name = CITY_HUBS.get(city_key, {}).get("name", city_key.title())
    return _SYSTEM_PROMPT_TEMPLATE.format(city_name=city_name)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_route_safety",
            "description": "Analyze safety of a walking route by sampling 5 points along it. Queries real OpenStreetMap data: streetlight density, lit/unlit road ratio, nearby POIs. Returns per-segment scores, the weakest segment, and a recommendation.",
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
            "description": "Query real OpenStreetMap data for a location: reverse-geocoded neighborhood name, streetlight count, lit road ratio, POI density, emergency service proximity, and composite safety score.",
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
    {
        "type": "function",
        "function": {
            "name": "escalate_emergency",
            "description": "Trigger an emergency alert if the user is in immediate danger or asks for urgent help. This notifies mission control and can dispatch assistance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string", "description": "Brief description of why the emergency is being escalated"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"], "description": "How urgent the situation is"},
                },
                "required": ["reasoning", "severity"],
            },
        },
    },
]

# ── Shared state (set by server.py) ──────────────────────────────────────────

_escort_state: dict = {}
_user_position: dict = {}
_current_city: str | None = None
_escalation_log: list[dict] = []
_escalation_callback = None


def set_shared_state(escort: dict, user_pos: dict, escalation_callback=None, city: str | None = None):
    global _escort_state, _user_position, _escalation_callback, _current_city
    _escort_state = escort
    _user_position = user_pos
    if escalation_callback is not None:
        _escalation_callback = escalation_callback
    if city is not None:
        _current_city = city


# ── Tool implementations ─────────────────────────────────────────────────────

def tool_get_route_safety(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> str:
    """Query real OSM data along the route: samples 5 points for streetlights, lit roads, POIs."""
    try:
        from geo_intel import compute_route_safety
        data = compute_route_safety(from_lat, from_lng, to_lat, to_lng)
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"safety_score": 5, "error": str(e), "recommendation": "Unable to analyze route"})


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
    """Query real OSM data: neighborhood name, streetlight density, POI types, safety score."""
    try:
        from geo_intel import compute_area_safety_score
        data = compute_area_safety_score(lat, lng)
        return json.dumps({
            "neighborhood": data.get("neighborhood", "Unknown"),
            "road": data.get("road", "Unknown"),
            "safety_score": data.get("safety_score", 5),
            "lighting_quality": data.get("lighting_quality", "unknown"),
            "streetlights_nearby": data.get("streetlights_nearby", 0),
            "foot_traffic": data.get("foot_traffic_level", "unknown"),
            "pois_nearby": data.get("pois_nearby", 0),
            "emergency_services": data.get("emergency_services_nearby", 0),
            "time_of_day": data.get("time_of_day", "unknown"),
        })
    except Exception as e:
        return json.dumps({"neighborhood": "Unknown", "error": str(e)})


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


def tool_escalate_emergency(reasoning: str, severity: str = "high") -> str:
    entry = {
        "origin": "louise",
        "reasoning": reasoning,
        "severity": severity,
        "timestamp": time.time(),
        "user_position": _user_position,
    }
    _escalation_log.append(entry)
    if _escalation_callback:
        _escalation_callback(entry)
    return json.dumps({
        "status": "escalated",
        "message": f"Emergency alert sent to mission control ({severity} severity). Help is on the way.",
        "alert_id": len(_escalation_log),
    })


TOOL_DISPATCH = {
    "get_route_safety": lambda args: tool_get_route_safety(**args),
    "get_escort_status": lambda args: tool_get_escort_status(),
    "get_area_info": lambda args: tool_get_area_info(args.get("lat", 0), args.get("lng", 0)),
    "get_safety_tips": lambda args: tool_get_safety_tips(args.get("context", "")),
    "escalate_emergency": lambda args: tool_escalate_emergency(args.get("reasoning", ""), args.get("severity", "high")),
}


# ── Agent execution ──────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 2


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

    messages = [{"role": "system", "content": _get_system_prompt()}]
    if conversation_history:
        messages.extend(conversation_history[-10:])
    messages.append({"role": "user", "content": user_message})

    tool_calls_made = []

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        for _round in range(MAX_TOOL_ROUNDS + 1):
            response = client.chat.complete(
                model=MISTRAL_FAST_MODEL,
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
