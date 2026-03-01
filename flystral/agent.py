"""
Flystral Agent — drone flight controller powered by Mistral.

Two inference modes:
  1. Fine-tuned model (BenBarr/flystral on HuggingFace) served via FLYSTRAL_ENDPOINT
     — LoRA fine-tuned Ministral 3B, outputs telemetry vectors from camera images.
  2. Base model fallback (ministral-3b-latest via Mistral API)
     — agentic mode with function calling for telemetry, threat, and route tools.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MISTRAL_API_KEY, MISTRAL_EDGE_MODEL, FLYSTRAL_ENDPOINT
from flystral.command_parser import VALID_COMMANDS, parse_velocity_output

SYSTEM_PROMPT = (
    "You are Flystral, a drone autopilot AI for a safety escort drone.\n\n"
    "PROCESS — follow these steps:\n"
    "1. Call get_drone_telemetry to check your altitude, speed, battery, and distance to user\n"
    "2. Call get_threat_assessment to get Helpstral's latest safety analysis\n"
    "3. Call get_route_progress to understand how far along the escort is\n"
    "4. Analyze the image for obstacles, terrain, overhead obstructions, and visibility\n"
    "5. Make a flight decision that balances FOUR competing priorities:\n\n"
    "TRADE-OFF ANALYSIS (explain your reasoning on these):\n"
    "a) PROTECTION — lower altitude + closer = better camera coverage of user, but more noise "
    "and risk of obstacles. At threat_level >= 6, protection overrides comfort.\n"
    "b) BATTERY — every altitude change and speed increase costs battery. If battery <= 30%, "
    "start conserving. If <= 15%, REPLAN to return regardless of threat.\n"
    "c) CAMERA COVERAGE — altitude affects field of view. Too low = narrow view, might miss "
    "threats approaching from sides. Too high = can't identify faces/details.\n"
    "d) USER COMFORT — at low threat, stay higher (25m+) and quieter. Don't hover 5m above "
    "someone in a safe area.\n\n"
    "Optimal altitude by threat level:\n"
    "- SAFE (1-3): 25-30m, speed 0.5-0.8, wide monitoring\n"
    "- CAUTION (4-6): 15-20m, speed 0.3-0.5, tighter follow\n"
    "- ELEVATED (7): 10-15m, speed 0.2-0.3, close escort\n"
    "- DISTRESS (8-10): HOVER 5-8m directly above, spotlight mode\n\n"
    "Final answer MUST be JSON:\n"
    "- scene_analysis: what you see in the drone camera image\n"
    "- threat_context: Helpstral's assessment and how you're adapting\n"
    "- command: FOLLOW, AVOID_LEFT, AVOID_RIGHT, CLIMB, DESCEND, HOVER, or REPLAN\n"
    "- param: string number (speed for FOLLOW, metres for spatial, seconds for HOVER)\n"
    "- reasoning: 2-3 sentences explaining the trade-off you made\n"
    "- altitude_adjust: integer -20 to +20 (justify the change)\n"
    "- next_check: what condition would change your decision"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_drone_telemetry",
            "description": "Get current drone telemetry: altitude (m), ground speed (m/s), battery percentage, heading (degrees), and distance to user (m).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_threat_assessment",
            "description": "Get Helpstral's latest safety assessment including threat_level (1-10), status (SAFE/CAUTION/DISTRESS), observations, and pattern. Use this to adapt flight behavior to threats.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_route_progress",
            "description": "Get escort route progress: percentage complete, estimated remaining distance, and ETA.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

DEFAULT_RESULT = {
    "scene_analysis": "No image available",
    "threat_context": "Unknown — using default",
    "command": "FOLLOW",
    "param": "0.5",
    "reasoning": "Default follow — no image data or API unavailable.",
    "altitude_adjust": 0,
    "next_check": "Await next frame",
}

DEFAULT_VELOCITY = {"vx": 2.0, "vy": 0.0, "vz": 0.0, "yaw_rate": 0.0}


# ── Fine-tuned model (remote endpoint) ──────────────────────────────────────

def _run_remote_endpoint(image_b64: str, heading_rad: float = 0.0) -> dict:
    """Call the fine-tuned Flystral model served from Colab GPU via ngrok."""
    import requests

    url = FLYSTRAL_ENDPOINT.rstrip("/") + "/predict"
    resp = requests.post(url, json={"image": image_b64}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    vel = {
        "vx": float(data.get("vx", 2.0)),
        "vy": float(data.get("vy", 0.0)),
        "vz": float(data.get("vz", 0.0)),
        "yaw_rate": float(data.get("yaw_rate", 0.0)),
    }
    offset = parse_velocity_output(vel, heading_rad)

    return {
        "mode": "velocity",
        "vx": offset["vx"],
        "vy": offset["vy"],
        "vz": offset["vz"],
        "yaw_rate": offset["yaw_rate"],
        "offset": offset,
        "raw": data.get("raw", ""),
        "model": "BenBarr/flystral",
        "inference_ms": data.get("inference_ms"),
        "timestamp": time.time(),
        "tool_calls_made": [],
        "source": "finetuned",
    }


# ── Shared state (set by server.py) ──────────────────────────────────────────

_telemetry_ref: dict = {}
_threat_ref: dict = {}
_route_progress_ref: float | None = None


def set_shared_state(telemetry: dict, threat: dict, route_progress: float | None):
    global _telemetry_ref, _threat_ref, _route_progress_ref
    _telemetry_ref = telemetry
    _threat_ref = threat
    _route_progress_ref = route_progress


# ── Tool implementations ─────────────────────────────────────────────────────

def tool_get_drone_telemetry() -> str:
    tel = _telemetry_ref or {}
    return json.dumps({
        "altitude_m": tel.get("alt", 25),
        "ground_speed_ms": tel.get("ground_speed", 0),
        "battery_pct": tel.get("battery_pct", 100),
        "heading_deg": tel.get("heading", 0),
        "distance_to_user_m": tel.get("distance_to_user", 15),
        "phase": tel.get("phase", "unknown"),
    })


def tool_get_threat_assessment() -> str:
    threat = _threat_ref or {}
    return json.dumps({
        "threat_level": threat.get("threat_level", 1),
        "status": threat.get("status", "SAFE"),
        "observations": threat.get("observations", []),
        "pattern": threat.get("pattern", "No pattern"),
        "reasoning": threat.get("reasoning", ""),
        "action": threat.get("action", "CONTINUE_MONITORING"),
    })


def tool_get_route_progress() -> str:
    pct = _route_progress_ref
    if pct is None:
        return json.dumps({"progress_pct": 0, "status": "no active route"})
    return json.dumps({
        "progress_pct": int(pct * 100),
        "remaining_pct": int((1 - pct) * 100),
        "status": "active",
    })


TOOL_DISPATCH = {
    "get_drone_telemetry": lambda args: tool_get_drone_telemetry(),
    "get_threat_assessment": lambda args: tool_get_threat_assessment(),
    "get_route_progress": lambda args: tool_get_route_progress(),
}


# ── JSON parsing ──────────────────────────────────────────────────────────────

def parse_structured_command(raw: str) -> dict:
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


# ── Agent execution ───────────────────────────────────────────────────────────

MAX_TOOL_ROUNDS = 3


def run_flystral_agent(
    image_b64: str,
    threat_assessment: dict | None = None,
    telemetry: dict | None = None,
    route_progress: float | None = None,
    heading_rad: float = 0.0,
) -> dict:
    """
    Run Flystral. Priority:
      1. Fine-tuned endpoint (FLYSTRAL_ENDPOINT) — BenBarr/flystral LoRA on Colab GPU
      2. Base model fallback (ministral-3b-latest) — agentic mode via Mistral API
    """
    set_shared_state(
        telemetry or {},
        threat_assessment or {},
        route_progress,
    )

    if FLYSTRAL_ENDPOINT:
        try:
            return _run_remote_endpoint(image_b64, heading_rad)
        except Exception as e:
            print(f"[Flystral] Endpoint failed, falling back to base model: {e}")

    if not MISTRAL_API_KEY:
        result = dict(DEFAULT_RESULT)
        result["mode"] = "discrete"
        tl = (threat_assessment or {}).get("threat_level", 1)
        if tl >= 8:
            result.update(command="HOVER", param="10", altitude_adjust=-15,
                          reasoning="DISTRESS detected — hovering above user.")
        elif tl >= 5:
            result.update(param="0.3", altitude_adjust=-5,
                          reasoning="Caution — slowing and lowering altitude.")
        result["source"] = "no_key_fallback"
        result["tool_calls_made"] = []
        return result

    model = MISTRAL_EDGE_MODEL

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": (
                    "Analyze this drone camera frame. Use your tools to check telemetry, "
                    "threat status, and route progress, then decide the next flight action as JSON."
                )},
            ],
        },
    ]

    tool_calls_made = []

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

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
                result = parse_structured_command(raw)
                result["mode"] = "discrete"
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
        result = parse_structured_command(raw)
        result["mode"] = "discrete"
        result["timestamp"] = time.time()
        result["tool_calls_made"] = tool_calls_made
        return result

    except Exception as e:
        return {**DEFAULT_RESULT, "mode": "discrete", "error": str(e), "timestamp": time.time(), "tool_calls_made": tool_calls_made}
