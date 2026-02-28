"""
Generate structured Helpstral training data (JSON assessments, not binary SAFE/DISTRESS).

Usage:
    python helpstral/dataset/generate_structured.py --output helpstral/dataset/helpstral_structured.jsonl --count 300

Each record uses the multi-agent format:
  system: "You are Helpstral..."
  user: [image, context]
  assistant: structured JSON assessment
"""

import argparse
import json
import random
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "You are Helpstral, a safety AI monitoring a drone escort camera feed protecting a person "
    "walking alone at night. Analyze the image with the provided context. "
    "Output a structured threat assessment as JSON."
)

SAFE_SCENARIOS = [
    {
        "observations": ["well-lit residential street", "no other pedestrians", "user walking at steady pace"],
        "pattern": "Consistent safe conditions for last {n} observations",
        "reasoning": "Normal residential environment with adequate lighting and no threats detected.",
    },
    {
        "observations": ["busy commercial area", "multiple pedestrians", "shops open with good lighting"],
        "pattern": "High foot traffic area, consistently safe",
        "reasoning": "Well-populated commercial zone with natural surveillance from other people.",
    },
    {
        "observations": ["main road with traffic", "streetlights functional", "clear sidewalk"],
        "pattern": "Standard urban transit route",
        "reasoning": "Main road with consistent lighting and traffic providing natural security.",
    },
    {
        "observations": ["park path with lamp posts", "jogger visible ahead", "open green space"],
        "pattern": "Park environment with other users present",
        "reasoning": "Well-maintained park path with functioning lights and other people present.",
    },
]

CAUTION_SCENARIOS = [
    {
        "observations": ["person following at 20m", "poorly lit side street", "user pace unchanged"],
        "pattern": "Same individual visible in last {n} frames, closing distance",
        "reasoning": "Potential follower detected — appeared 30s ago and has maintained trajectory.",
    },
    {
        "observations": ["dimly lit underpass ahead", "graffiti on walls", "no other pedestrians visible"],
        "pattern": "Entering low-visibility area",
        "reasoning": "User approaching poorly lit underpass with limited escape routes.",
    },
    {
        "observations": ["group of 3 loitering on corner", "user approaching", "moderate lighting"],
        "pattern": "Stationary group in user's path",
        "reasoning": "Group ahead — monitoring body language and user's reaction.",
    },
]

DISTRESS_SCENARIOS = [
    {
        "observations": ["physical altercation visible", "user on ground", "attacker standing over"],
        "pattern": "Sudden transition from CAUTION to active threat",
        "reasoning": "Active physical assault detected — immediate emergency response required.",
    },
    {
        "observations": ["user running", "two individuals pursuing", "screaming detected"],
        "pattern": "Pursuit situation escalating from previous CAUTION",
        "reasoning": "User in active flight from pursuers — emergency hover and alert required.",
    },
    {
        "observations": ["user collapsed", "no movement detected", "isolated location"],
        "pattern": "Sudden stop after normal walking pattern",
        "reasoning": "User has collapsed or is incapacitated — medical emergency possible.",
    },
]

CONTEXTS = [
    "Night, residential area. Previous assessments: [{prev}]. Escort progress: {pct}% complete.",
    "Evening, commercial district. Previous assessments: [{prev}]. Escort progress: {pct}% complete.",
    "Night, park path. Previous assessments: [{prev}]. Escort progress: {pct}% complete.",
    "Late night, urban area. Previous assessments: [{prev}]. Escort progress: {pct}% complete.",
]

ACTIONS = {
    "SAFE": ["CONTINUE_MONITORING"],
    "CAUTION": ["INCREASE_SCAN_RATE", "ALERT_USER"],
    "DISTRESS": ["ACTIVATE_SPOTLIGHT", "EMERGENCY_HOVER"],
}


def generate_record(status: str, image_placeholder: str = "BASE64_IMAGE_HERE") -> dict:
    if status == "SAFE":
        threat_level = random.randint(1, 3)
        scenario = random.choice(SAFE_SCENARIOS)
    elif status == "CAUTION":
        threat_level = random.randint(4, 7)
        scenario = random.choice(CAUTION_SCENARIOS)
    else:
        threat_level = random.randint(8, 10)
        scenario = random.choice(DISTRESS_SCENARIOS)

    n_prev = random.randint(2, 5)
    prev_statuses = ["SAFE"] * n_prev if status == "SAFE" else (
        ["SAFE"] * (n_prev - 1) + ["CAUTION"] if status == "CAUTION" else
        ["SAFE", "CAUTION", "CAUTION"]
    )
    pct = random.randint(10, 90)
    context = random.choice(CONTEXTS).format(
        prev=", ".join(prev_statuses),
        pct=pct,
    )

    assessment = {
        "threat_level": threat_level,
        "status": status,
        "observations": scenario["observations"],
        "pattern": scenario["pattern"].format(n=n_prev),
        "reasoning": scenario["reasoning"],
        "action": random.choice(ACTIONS[status]),
    }

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
            {"role": "assistant", "content": json.dumps(assessment)},
        ]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="helpstral/dataset/helpstral_structured.jsonl")
    parser.add_argument("--count", type=int, default=300)
    args = parser.parse_args()

    records = []
    n_safe = int(args.count * 0.6)
    n_caution = int(args.count * 0.25)
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
