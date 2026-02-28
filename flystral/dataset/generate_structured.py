"""
Generate structured Flystral training data (JSON flight commands with threat awareness).

Usage:
    python flystral/dataset/generate_structured.py --output flystral/dataset/flystral_structured.jsonl --count 200

Each record uses the multi-agent format:
  system: "You are Flystral..."
  user: [image, telemetry + Helpstral context]
  assistant: structured JSON flight command
"""

import argparse
import json
import random
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "You are Flystral, a drone autopilot AI. Analyze the drone camera image with the provided "
    "telemetry and threat context. Output a structured flight command as JSON."
)

SAFE_COMMANDS = [
    {
        "scene_analysis": "Clear urban street, good visibility, no obstacles",
        "threat_context": "SAFE — no threats detected",
        "command": "FOLLOW", "param": "0.6",
        "reasoning": "Normal conditions, maintaining standard escort distance and speed.",
        "altitude_adjust": 0,
        "next_check": "Continue routine monitoring",
    },
    {
        "scene_analysis": "Wide boulevard, pedestrians visible, well-lit",
        "threat_context": "SAFE — area well populated",
        "command": "FOLLOW", "param": "0.7",
        "reasoning": "Safe area with good visibility, can maintain higher speed.",
        "altitude_adjust": 0,
        "next_check": "Standard monitoring interval",
    },
]

CAUTION_COMMANDS = [
    {
        "scene_analysis": "Narrow alley, limited visibility, person 20m behind user",
        "threat_context": "ELEVATED — adapting to protective mode",
        "command": "FOLLOW", "param": "0.3",
        "reasoning": "Slowing to maintain close proximity. Threat detected behind user — positioning drone between user and potential threat.",
        "altitude_adjust": -8,
        "next_check": "If threat persists 2 more frames, activate spotlight and hover",
    },
    {
        "scene_analysis": "Dimly lit park path, shadows on left",
        "threat_context": "CAUTION — low visibility area",
        "command": "FOLLOW", "param": "0.4",
        "reasoning": "Reducing speed and altitude for better camera coverage in low-light area.",
        "altitude_adjust": -5,
        "next_check": "Monitor for obstacles and threats in shadows",
    },
]

DISTRESS_COMMANDS = [
    {
        "scene_analysis": "Active confrontation visible, user in danger",
        "threat_context": "CRITICAL — DISTRESS confirmed by Helpstral",
        "command": "HOVER", "param": "10",
        "reasoning": "Emergency hover directly above user. Activating spotlight. Helpstral confirmed active distress.",
        "altitude_adjust": -15,
        "next_check": "Maintain hover until emergency services respond or threat clears",
    },
    {
        "scene_analysis": "User running, pursuers visible",
        "threat_context": "CRITICAL — active pursuit detected",
        "command": "FOLLOW", "param": "0.2",
        "reasoning": "Matching user speed while maintaining very close proximity. Emergency beacon activated.",
        "altitude_adjust": -12,
        "next_check": "If user stops, switch to HOVER immediately",
    },
]

LOW_BATTERY_COMMAND = {
    "scene_analysis": "Standard conditions",
    "threat_context": "Battery critical — returning to hub",
    "command": "REPLAN", "param": "0",
    "reasoning": "Battery at critical level. Initiating return to hub — safety of drone takes priority.",
    "altitude_adjust": 5,
    "next_check": "Confirm return path clear",
}

THREAT_LEVELS = {
    "SAFE": (1, 3, "SAFE", "No pattern"),
    "CAUTION": (5, 7, "CAUTION", "Individual following user for 3 frames"),
    "DISTRESS": (8, 10, "DISTRESS", "Active threat confirmed"),
}


def generate_record(threat_category: str, image_placeholder: str = "BASE64_IMAGE_HERE") -> dict:
    tl_min, tl_max, status, pattern = THREAT_LEVELS[threat_category]
    threat_level = random.randint(tl_min, tl_max)

    alt = random.randint(15, 35)
    speed = round(random.uniform(2, 12), 1)
    battery = random.randint(40, 95)
    heading = random.randint(0, 359)
    pct = random.randint(10, 90)

    if battery <= 20:
        flight_cmd = dict(LOW_BATTERY_COMMAND)
    elif threat_category == "SAFE":
        flight_cmd = dict(random.choice(SAFE_COMMANDS))
    elif threat_category == "CAUTION":
        flight_cmd = dict(random.choice(CAUTION_COMMANDS))
    else:
        flight_cmd = dict(random.choice(DISTRESS_COMMANDS))

    helpstral_ctx = json.dumps({"threat_level": threat_level, "status": status, "pattern": pattern})
    context = (
        f"Telemetry: alt={alt}m, speed={speed}m/s, battery={battery}%, heading={heading:03d}. "
        f"Helpstral: {helpstral_ctx}. Route: {pct}% complete."
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_placeholder}"}},
                    {"type": "text", "text": f"Context: {context}"},
                ],
            },
            {"role": "assistant", "content": json.dumps(flight_cmd)},
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="flystral/dataset/flystral_structured.jsonl")
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()

    records = []
    n_safe = int(args.count * 0.5)
    n_caution = int(args.count * 0.3)
    n_distress = args.count - n_safe - n_caution

    for _ in range(n_safe):
        records.append(generate_record("SAFE"))
    for _ in range(n_caution):
        records.append(generate_record("CAUTION"))
    for _ in range(n_distress):
        records.append(generate_record("DISTRESS"))

    random.shuffle(records)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"Generated {len(records)} records: {n_safe} SAFE, {n_caution} CAUTION, {n_distress} DISTRESS")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()
