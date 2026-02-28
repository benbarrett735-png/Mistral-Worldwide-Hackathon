"""
Build Flystral (and optionally Helpstral) JSONL from a public drone dataset.

Uses VisDrone2019-DET from Hugging Face via FiftyOne. Images contain
pedestrians, people, cars, etc. We derive command labels from detection
counts (e.g. pedestrian visible + few obstacles -> FOLLOW; many objects -> HOVER).

Requirements:
  pip install fiftyone requests

Then run from this directory:
  python from_public_drone_dataset.py --max-per-class 100 --out flystral_dataset.jsonl

First run will download ~2GB (VisDrone). Uses PEXELS_API_KEY only for the
other fetch script; this script does not need it.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

# VisDrone class IDs (from official format): 0=ignored, 1=pedestrian, 2=people, 3=bicycle, 4=car, 5=van, 6=truck, ...
PEDESTRIAN_LABELS = {"pedestrian", "people"}
OBSTACLE_LABELS = {"car", "van", "truck", "bus", "motor", "bicycle", "tricycle", "awning-tricycle"}


def load_visdrone(max_samples: int = 500):
    """Load VisDrone from Hugging Face via FiftyOne. Returns list of (image_path, detections)."""
    try:
        import fiftyone as fo
        import fiftyone.utils.huggingface as fouh
    except ImportError:
        print("Install FiftyOne: pip install fiftyone", file=sys.stderr)
        sys.exit(1)

    print("Loading VisDrone2019-DET from Hugging Face (first time may download ~2GB)...")
    dataset = fouh.load_from_hub("Voxel51/VisDrone2019-DET", max_samples=max_samples)
    samples = list(dataset.iter_samples(autosave=False))
    out = []
    for s in samples:
        filepath = s.filepath
        if not filepath or not Path(filepath).exists():
            continue
        dets = s.ground_truth
        if dets is None:
            out.append((filepath, []))
            continue
        labels = []
        if hasattr(dets, "detections"):
            for d in dets.detections:
                lbl = getattr(d, "label", None) or getattr(d, "label_id", None)
                if lbl is not None:
                    labels.append(str(lbl).lower())
        out.append((filepath, labels))
    return out


def derive_command(labels: list[str]) -> tuple[str, str]:
    """Map detection labels to a single Flystral command."""
    ped_count = sum(1 for L in labels if L in PEDESTRIAN_LABELS)
    obst_count = sum(1 for L in labels if L in OBSTACLE_LABELS)
    if obst_count >= 3:
        return "HOVER", "3"
    if obst_count >= 1 and ped_count >= 1:
        return "AVOID_LEFT", "2"  # obstacle + person -> avoid
    if ped_count >= 2:
        return "HOVER", "2"
    if ped_count >= 1:
        return "FOLLOW", "0.6"
    if obst_count >= 1:
        return "CLIMB", "5"
    return "HOVER", "2"  # empty or unclear


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-samples", type=int, default=500, help="Max images to load from VisDrone")
    parser.add_argument("--max-per-class", type=int, default=100, help="Cap per derived command class (for balance)")
    parser.add_argument("--out", default="flystral_dataset.jsonl", help="Output JSONL path")
    args = parser.parse_args()

    here = Path(__file__).parent
    out_file = here / args.out

    samples = load_visdrone(max_samples=args.max_samples)
    print(f"Loaded {len(samples)} samples")

    USER_PROMPT = (
        "You are Flystral, a drone autopilot AI. "
        "Analyze this drone camera image and output exactly one command from:\n"
        "FOLLOW|<speed 0.1-1.0>, AVOID_LEFT|<dist_m>, AVOID_RIGHT|<dist_m>, "
        "CLIMB|<meters>, HOVER|<seconds>, REPLAN|0, DESCEND|<meters>\n"
        "Respond with the command only. Example: FOLLOW|0.7"
    )

    from collections import defaultdict
    by_cmd = defaultdict(list)  # (cmd, param) -> list of (path, labels)
    for path, labels in samples:
        cmd, param = derive_command(labels)
        key = (cmd, param)
        if len(by_cmd[key]) >= args.max_per_class:
            continue
        by_cmd[key].append((path, labels))

    records = []
    for (cmd, param), items in by_cmd.items():
        for path, _ in items:
            p = Path(path)
            if not p.exists():
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            content = [
                {"type": "text", "text": USER_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]
            records.append({
                "messages": [
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": f"{cmd}|{param}"},
                ]
            })

    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    from collections import Counter
    counts = Counter(r["messages"][1]["content"].split("|")[0] for r in records)
    print(f"Wrote {len(records)} records to {out_file}")
    for cmd, n in sorted(counts.items()):
        print(f"  {cmd}: {n}")
    print("Run: python train.py --dataset dataset/flystral_dataset.jsonl")


if __name__ == "__main__":
    main()
