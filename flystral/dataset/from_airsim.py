"""
Convert AirSim drone flight recordings to Flystral fine-tuning JSONL.

AirSim dataset structure (expected):
    airsim_data/
        images/
            img_000000.png
            img_000001.png
            ...
        airsim_rec.txt   (or commands.csv)

Each line in the recording file maps an image to velocity commands:
    TimeStamp  ImageFile  vx  vy  vz  yaw_rate  ...

Output: flystral_dataset.jsonl — each record is a Mistral chat-format message
with the drone camera image and the target velocity vector as the assistant response.

Usage:
    python from_airsim.py --data-dir ./airsim_data --out flystral_dataset.jsonl
    python from_airsim.py --data-dir ./airsim_data --max-samples 5000
"""

import argparse
import base64
import csv
import json
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "Analyze this drone camera image. Output a JSON velocity command: "
    '{"vx": forward_speed, "vy": lateral_speed, "vz": vertical_speed, "yaw_rate": turn_rate}. '
    "Positive vx = forward, positive vy = right, positive vz = up. Values in m/s, yaw in deg/s."
)


def load_airsim_recording(data_dir: Path) -> list[dict]:
    """
    Parse AirSim recording file. Supports both tab-separated airsim_rec.txt
    and CSV formats. Returns list of {image_path, vx, vy, vz, yaw_rate}.
    """
    records = []

    rec_file = data_dir / "airsim_rec.txt"
    csv_file = data_dir / "commands.csv"
    labels_file = data_dir / "labels.csv"

    if rec_file.exists():
        records = _parse_tsv(rec_file, data_dir)
    elif csv_file.exists():
        records = _parse_csv(csv_file, data_dir)
    elif labels_file.exists():
        records = _parse_csv(labels_file, data_dir)
    else:
        txt_files = list(data_dir.glob("*.txt")) + list(data_dir.glob("*.csv"))
        if txt_files:
            for f in txt_files:
                try:
                    records = _parse_csv(f, data_dir)
                    if records:
                        print(f"  Parsed recording from: {f.name}")
                        break
                except Exception:
                    continue

        if not records:
            print(f"No recording file found in {data_dir}")
            print("Expected: airsim_rec.txt, commands.csv, or labels.csv")
            sys.exit(1)

    return records


def _parse_tsv(path: Path, data_dir: Path) -> list[dict]:
    """Parse AirSim's native tab-separated recording format."""
    records = []
    with open(path) as f:
        header = f.readline().strip().split("\t")
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 5:
                continue
            row = dict(zip(header, parts))

            img_name = row.get("ImageFile", row.get("image", ""))
            img_path = data_dir / "images" / img_name
            if not img_path.exists():
                img_path = data_dir / img_name
            if not img_path.exists():
                continue

            records.append({
                "image_path": str(img_path),
                "vx": float(row.get("vx", row.get("VX", 0))),
                "vy": float(row.get("vy", row.get("VY", 0))),
                "vz": float(row.get("vz", row.get("VZ", 0))),
                "yaw_rate": float(row.get("yaw_rate", row.get("YawRate", row.get("yaw", 0)))),
            })
    return records


def _parse_csv(path: Path, data_dir: Path) -> list[dict]:
    """Parse CSV format with columns for image and velocity components."""
    records = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_name = (
                row.get("ImageFile") or row.get("image") or
                row.get("filename") or row.get("img") or ""
            )
            if not img_name:
                continue

            img_path = data_dir / "images" / img_name
            if not img_path.exists():
                img_path = data_dir / img_name
            if not img_path.exists():
                continue

            try:
                records.append({
                    "image_path": str(img_path),
                    "vx": float(row.get("vx", row.get("VX", row.get("velocity_x", 0)))),
                    "vy": float(row.get("vy", row.get("VY", row.get("velocity_y", 0)))),
                    "vz": float(row.get("vz", row.get("VZ", row.get("velocity_z", 0)))),
                    "yaw_rate": float(row.get("yaw_rate", row.get("YawRate", row.get("yaw", 0)))),
                })
            except (ValueError, TypeError):
                continue
    return records


def image_to_base64(image_path: str) -> str:
    """Read image file and return base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def record_to_jsonl(rec: dict) -> dict:
    """Convert a single AirSim record to Mistral fine-tuning JSONL format."""
    img_b64 = image_to_base64(rec["image_path"])

    ext = Path(rec["image_path"]).suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
        ext.lstrip("."), "image/png"
    )

    assistant_content = json.dumps({
        "vx": round(rec["vx"], 3),
        "vy": round(rec["vy"], 3),
        "vz": round(rec["vz"], 3),
        "yaw_rate": round(rec["yaw_rate"], 3),
    })

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                    {"type": "text", "text": "Output velocity command for this frame."},
                ],
            },
            {"role": "assistant", "content": assistant_content},
        ]
    }


def main():
    parser = argparse.ArgumentParser(description="Convert AirSim data to Flystral JSONL")
    parser.add_argument("--data-dir", required=True, help="Path to AirSim data directory")
    parser.add_argument("--out", default="flystral_dataset.jsonl", help="Output JSONL path")
    parser.add_argument("--max-samples", type=int, default=None, help="Limit number of samples")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Data directory not found: {data_dir}")
        sys.exit(1)

    print(f"Loading AirSim recordings from {data_dir}...")
    records = load_airsim_recording(data_dir)
    print(f"  Found {len(records)} records")

    if args.max_samples and len(records) > args.max_samples:
        import random
        random.shuffle(records)
        records = records[:args.max_samples]
        print(f"  Sampled {len(records)} records")

    import numpy as np
    vx = [r["vx"] for r in records]
    vy = [r["vy"] for r in records]
    vz = [r["vz"] for r in records]
    yaw = [r["yaw_rate"] for r in records]
    print(f"\nVelocity statistics:")
    print(f"  vx: mean={np.mean(vx):.2f}, std={np.std(vx):.2f}")
    print(f"  vy: mean={np.mean(vy):.2f}, std={np.std(vy):.2f}")
    print(f"  vz: mean={np.mean(vz):.2f}, std={np.std(vz):.2f}")
    print(f"  yaw: mean={np.mean(yaw):.2f}, std={np.std(yaw):.2f}")

    out_path = Path(args.out)
    print(f"\nConverting to JSONL: {out_path}")
    written = 0
    errors = 0

    with open(out_path, "w") as f:
        for i, rec in enumerate(records):
            try:
                jsonl_record = record_to_jsonl(rec)
                f.write(json.dumps(jsonl_record) + "\n")
                written += 1
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  Error on record {i}: {e}")

            if (i + 1) % 500 == 0:
                print(f"  Processed {i + 1}/{len(records)}")

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\nDone: {written} records written to {out_path} ({size_mb:.1f} MB)")
    if errors:
        print(f"  {errors} records skipped due to errors")


if __name__ == "__main__":
    main()
