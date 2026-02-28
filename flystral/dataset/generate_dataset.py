"""
Flystral vision-to-command dataset generator.

Builds JSONL for fine-tuning Pixtral 12B as an aerial autopilot.
Each record: drone camera image + correct autopilot command.

Commands:
  FOLLOW|<speed>       - Person visible ahead, follow at speed (0.1-1.0)
  AVOID_LEFT|<dist>    - Obstacle right side, dodge left
  AVOID_RIGHT|<dist>   - Obstacle left side, dodge right
  CLIMB|<meters>       - Obstacle ahead, climb over
  HOVER|<seconds>      - Person stopped or unclear, hold position
  REPLAN|0             - Person deviated from expected path
  DESCEND|<meters>     - Too high, descend to maintain escort altitude

Image scenarios (synthetic using URL-based images):
  - Clear path: FOLLOW|0.7
  - Tree/post on right: AVOID_LEFT|2
  - Tree/post on left: AVOID_RIGHT|2
  - Wall/building ahead: CLIMB|5
  - Person stopped: HOVER|3
  - Empty frame: HOVER|5
  - Person off to side: REPLAN|0

Usage:
  python generate_dataset.py               # from local images in ./images/
  python generate_dataset.py --synthetic   # URL-based records, no local images
"""

import argparse
import base64
import json
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "You are Flystral, an AI autopilot for a safety escort drone flying over city streets. "
    "Given a drone camera image, output exactly one autopilot command."
)

COMMAND_DESCRIPTIONS = {
    "FOLLOW": "Person visible ahead, no obstacles, follow them",
    "AVOID_LEFT": "Obstacle on right side of frame (post/tree/vehicle), move drone left to avoid",
    "AVOID_RIGHT": "Obstacle on left side of frame, move drone right to avoid",
    "CLIMB": "Obstacle directly ahead (building/bridge/tree), climb over",
    "HOVER": "Person not visible, stopped, or scene unclear; hold position",
    "REPLAN": "Person has deviated significantly from expected route; replan path",
    "DESCEND": "Drone too high, descend to maintain escort altitude of 25m",
}

# Synthetic image -> command mapping using public aerial/street images
# Format: (image_url, command, param, scenario_description)
SYNTHETIC_SCENARIOS = [
    # FOLLOW scenarios: clear street view from above
    ("https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?w=640", "FOLLOW", "0.7", "Clear city street from above, person walking"),
    ("https://images.unsplash.com/photo-1444723121867-7a241cacace9?w=640", "FOLLOW", "0.6", "Wide boulevard, no obstacles"),
    ("https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=640", "FOLLOW", "0.5", "Night street, person visible"),
    ("https://images.unsplash.com/photo-1480714378408-67cf0d13bc1b?w=640", "FOLLOW", "0.8", "Daytime street, clear path"),
    ("https://images.unsplash.com/photo-1499856871958-5b9627545d1a?w=640", "FOLLOW", "0.6", "City walkway with person"),
    ("https://images.unsplash.com/photo-1505761671935-60b3a7427bad?w=640", "FOLLOW", "0.7", "Street level sidewalk"),
    ("https://images.unsplash.com/photo-1514565131-fce0801e6174?w=640", "FOLLOW", "0.5", "Night alley, person ahead"),
    ("https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=640", "FOLLOW", "0.6", "Open area, person walking"),

    # AVOID_LEFT (obstacle on right)
    ("https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=640", "AVOID_LEFT", "2", "Lamppost on right side of path"),
    ("https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=640", "AVOID_LEFT", "3", "Tree on right, clear left"),

    # AVOID_RIGHT (obstacle on left)
    ("https://images.unsplash.com/photo-1444084316824-dc26d6657664?w=640", "AVOID_RIGHT", "2", "Parked vehicle on left"),
    ("https://images.unsplash.com/photo-1553361371-9b22f78e8b1d?w=640", "AVOID_RIGHT", "2.5", "Scaffolding on left side"),

    # CLIMB (obstacle ahead)
    ("https://images.unsplash.com/photo-1486325212027-8081e485255e?w=640", "CLIMB", "5", "Building wall ahead, need to climb over"),
    ("https://images.unsplash.com/photo-1518791841217-8f162f1912da?w=640", "CLIMB", "8", "Bridge or overpass ahead"),
    ("https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=640", "CLIMB", "5", "Dense tree canopy ahead"),

    # HOVER
    ("https://images.unsplash.com/photo-1531804402-b72a8e8c019a?w=640", "HOVER", "3", "Person has stopped, holding position"),
    ("https://images.unsplash.com/photo-1550358864-518f202c02ba?w=640", "HOVER", "5", "Scene unclear, fog or blur"),
    ("https://images.unsplash.com/photo-1543310465-c577e7c0a8ac?w=640", "HOVER", "4", "Person not visible in frame"),

    # REPLAN
    ("https://images.unsplash.com/photo-1425421669292-0c3da3b8f529?w=640", "REPLAN", "0", "Person has turned onto side street"),
    ("https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=640", "REPLAN", "0", "User deviated to park path"),

    # DESCEND
    ("https://images.unsplash.com/photo-1506146332389-18140dc7b2fb?w=640", "DESCEND", "5", "Aerial view too high, person tiny"),
    ("https://images.unsplash.com/photo-1511739001486-6bfe10ce785f?w=640", "DESCEND", "3", "High altitude, need to descend"),
]

USER_PROMPT_TEMPLATE = (
    "You are Flystral, a drone autopilot AI. "
    "Analyze this drone camera image and output exactly one command from:\n"
    "FOLLOW|<speed 0.1-1.0>, AVOID_LEFT|<dist_m>, AVOID_RIGHT|<dist_m>, "
    "CLIMB|<meters>, HOVER|<seconds>, REPLAN|0, DESCEND|<meters>\n"
    "Respond with the command only. Example: FOLLOW|0.7"
)


def make_record(image_url: str, command: str, param: str) -> dict:
    label = f"{command}|{param}"
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT_TEMPLATE},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
            {"role": "assistant", "content": label},
        ]
    }


def make_record_local(image_b64: str, command: str, param: str) -> dict:
    label = f"{command}|{param}"
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT_TEMPLATE},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            },
            {"role": "assistant", "content": label},
        ]
    }


def generate_synthetic(out_file: Path):
    records = [make_record(url, cmd, param) for url, cmd, param, _ in SYNTHETIC_SCENARIOS]
    print(f"Generated {len(records)} synthetic Flystral records")
    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Saved to {out_file}")
    print("\nCommand distribution:")
    from collections import Counter
    counts = Counter(cmd for _, cmd, _, _ in SYNTHETIC_SCENARIOS)
    for cmd, n in sorted(counts.items()):
        print(f"  {cmd}: {n}")


def generate_from_images(images_dir: Path, out_file: Path):
    """
    Load images from labeled subdirs:
      images/follow/, images/avoid_left/, images/climb/, etc.
    Each image gets the command matching its folder name.
    """
    FOLDER_COMMANDS = {
        "follow":       ("FOLLOW", "0.7"),
        "avoid_left":   ("AVOID_LEFT", "2"),
        "avoid_right":  ("AVOID_RIGHT", "2"),
        "climb":        ("CLIMB", "5"),
        "hover":        ("HOVER", "3"),
        "replan":       ("REPLAN", "0"),
        "descend":      ("DESCEND", "5"),
    }

    records = []
    for folder, (cmd, param) in FOLDER_COMMANDS.items():
        d = images_dir / folder
        if not d.exists():
            continue
        for img in sorted(d.glob("*.jpg")) + sorted(d.glob("*.png")):
            b64 = base64.b64encode(img.read_bytes()).decode()
            records.append(make_record_local(b64, cmd, param))

    print(f"Built {len(records)} Flystral records from local images")
    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", action="store_true", help="Generate from public URLs (no local images)")
    parser.add_argument("--images-dir", default="images", help="Directory with command-labeled subdirs")
    parser.add_argument("--out", default="flystral_dataset.jsonl", help="Output JSONL file")
    args = parser.parse_args()

    here = Path(__file__).parent
    out_file = here / args.out

    if args.synthetic:
        generate_synthetic(out_file)
    else:
        images_dir = here / args.images_dir
        if not images_dir.exists():
            print(f"Images dir not found: {images_dir}")
            print("Run with --synthetic for URL-based synthetic records")
            sys.exit(1)
        generate_from_images(images_dir, out_file)
