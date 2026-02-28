"""
Helpstral Agent — structured safety monitor with memory, context, and tool use.

Produces structured JSON assessments instead of binary SAFE/DISTRESS.
Maintains a sliding window of recent assessments for pattern detection.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HELPSTRAL_MODEL_ID, MISTRAL_API_KEY

SYSTEM_PROMPT = (
    "You are Helpstral, a safety AI monitoring a drone escort camera feed protecting a person "
    "walking alone at night. Analyze the image with the provided context.\n\n"
    "You MUST respond with ONLY a valid JSON object (no markdown, no explanation) with these fields:\n"
    "- threat_level: integer 1-10 (1=completely safe, 5=caution, 8+=distress/danger)\n"
    "- status: one of SAFE, CAUTION, DISTRESS\n"
    "- observations: array of 2-4 short strings describing what you see\n"
    "- pattern: string describing any patterns across recent assessments (or 'No pattern' if first frame)\n"
    "- reasoning: 1-2 sentence explanation of your assessment\n"
    "- action: one of CONTINUE_MONITORING, INCREASE_SCAN_RATE, ALERT_USER, ACTIVATE_SPOTLIGHT, EMERGENCY_HOVER\n\n"
    "Example output:\n"
    '{"threat_level": 2, "status": "SAFE", "observations": ["well-lit street", "no other pedestrians"], '
    '"pattern": "Consistent safe conditions", "reasoning": "Normal urban environment with good visibility.", '
    '"action": "CONTINUE_MONITORING"}'
)

VALID_STATUSES = {"SAFE", "CAUTION", "DISTRESS"}
VALID_ACTIONS = {
    "CONTINUE_MONITORING", "INCREASE_SCAN_RATE", "ALERT_USER",
    "ACTIVATE_SPOTLIGHT", "EMERGENCY_HOVER"
}

DEFAULT_ASSESSMENT = {
    "threat_level": 1,
    "status": "SAFE",
    "observations": ["No image available or analysis failed"],
    "pattern": "No pattern",
    "reasoning": "Default safe assessment — no image data or API unavailable.",
    "action": "CONTINUE_MONITORING",
}


def get_location_context(lat: float, lng: float) -> dict:
    """Return area context for a location. In production, would query a GIS/POI API."""
    hour = datetime.now().hour
    time_of_day = "night" if hour < 6 or hour >= 20 else "evening" if hour >= 17 else "day"
    lighting = "low" if time_of_day == "night" else "moderate" if time_of_day == "evening" else "good"

    if 48.85 <= lat <= 48.87 and 2.33 <= lng <= 2.35:
        area_type = "central Paris — tourist area, well-lit main roads"
    elif 48.87 <= lat <= 48.89:
        area_type = "northern Paris — mixed residential and commercial"
    else:
        area_type = "urban residential area"

    return {
        "area_type": area_type,
        "lighting_estimate": lighting,
        "time_of_day": time_of_day,
        "hour": hour,
    }


def format_context(
    recent_assessments: list[dict],
    location: Optional[dict] = None,
    route_progress: Optional[float] = None,
) -> str:
    """Build the text context string that accompanies the image."""
    parts = []

    loc_ctx = location or {}
    parts.append(
        f"Time: {loc_ctx.get('time_of_day', 'unknown')}. "
        f"Area: {loc_ctx.get('area_type', 'unknown')}. "
        f"Lighting: {loc_ctx.get('lighting_estimate', 'unknown')}."
    )

    if recent_assessments:
        recent_statuses = [a.get("status", "SAFE") for a in recent_assessments[-5:]]
        parts.append(f"Previous assessments: {recent_statuses}.")
        last = recent_assessments[-1]
        if last.get("threat_level", 1) >= 5:
            parts.append(f"Last alert: threat_level={last['threat_level']}, pattern='{last.get('pattern', '')}'.")
    else:
        parts.append("No previous assessments (first frame).")

    if route_progress is not None:
        parts.append(f"Escort progress: {int(route_progress * 100)}% complete.")

    return " ".join(parts)


def parse_structured_assessment(raw: str) -> dict:
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


def run_helpstral_agent(
    image_b64: str,
    recent_assessments: list[dict] | None = None,
    location: dict | None = None,
    route_progress: float | None = None,
) -> dict:
    """
    Run the Helpstral agent: image + context → structured threat assessment.
    Returns a dict with threat_level, status, observations, pattern, reasoning, action.
    """
    if not MISTRAL_API_KEY:
        return {**DEFAULT_ASSESSMENT, "source": "no_key_fallback"}

    context_text = format_context(
        recent_assessments or [],
        location,
        route_progress,
    )

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        response = client.chat.complete(
            model=HELPSTRAL_MODEL_ID,
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
        result = parse_structured_assessment(raw)
        result["timestamp"] = time.time()
        return result

    except Exception as e:
        return {**DEFAULT_ASSESSMENT, "error": str(e), "timestamp": time.time()}
