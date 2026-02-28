"""
Helpstroll distress detection dataset generator.

Builds a JSONL file formatted for Mistral vision fine-tuning (Pixtral 12B).
Each record: a user/assistant pair where:
  - user: safety-AI prompt + base64 image
  - assistant: "DISTRESS" or "SAFE"

Image sources (download with --download flag):
  DISTRESS: struggle, person on ground, aggressive posture, dark alley confrontation
  SAFE: person walking normally, well-lit streets, relaxed posture

Usage:
  python generate_dataset.py                  # generate JSONL from images in ./images/
  python generate_dataset.py --download       # download sample images first (requires requests)
  python generate_dataset.py --synthetic      # generate a small synthetic JSONL for testing (no images)
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

SYSTEM_PROMPT = (
    "You are Helpstroll, a safety AI watching over a person walking alone at night. "
    "Analyze the image from the person's surroundings or camera. "
    "Respond with ONLY one word: DISTRESS or SAFE."
)

USER_PROMPT = (
    "Analyze this image. Is the person in danger or distress? "
    "Respond with exactly one word: DISTRESS or SAFE."
)

# Sample image URLs for distress / safe scenarios
# These are royalty-free images from Unsplash / Pexels / public domain
DISTRESS_URLS = [
    "https://images.unsplash.com/photo-1516585427167-9f4af9627e6c?w=640",  # dark alley
    "https://images.unsplash.com/photo-1555529669-e69e7aa0ba9a?w=640",  # person alone dark
    "https://images.unsplash.com/photo-1588776814546-1ffbb7d47b56?w=640",
    "https://images.unsplash.com/photo-1504680177321-2e6a879aac86?w=640",
    "https://images.unsplash.com/photo-1498050108023-c5249f4df085?w=640",
]

SAFE_URLS = [
    "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=640",  # person walking
    "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=640",  # well-lit street
    "https://images.unsplash.com/photo-1544717305-2782549b5136?w=640",
    "https://images.unsplash.com/photo-1517849845537-4d257902454a?w=640",
    "https://images.unsplash.com/photo-1501854140801-50d01698950b?w=640",  # park walking
]


def encode_image(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def make_record(image_b64: str, label: str, image_url: str = None) -> dict:
    content = [{"type": "text", "text": USER_PROMPT}]
    if image_url:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    else:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})

    return {
        "messages": [
            {"role": "user", "content": content},
            {"role": "assistant", "content": label},
        ]
    }


def download_images(out_dir: Path):
    try:
        import requests
    except ImportError:
        print("pip install requests  # needed for --download", file=sys.stderr)
        sys.exit(1)

    for i, url in enumerate(DISTRESS_URLS):
        p = out_dir / "distress" / f"distress_{i+1:03d}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            print(f"Downloading {url} -> {p}")
            r = requests.get(url, timeout=15)
            p.write_bytes(r.content)

    for i, url in enumerate(SAFE_URLS):
        p = out_dir / "safe" / f"safe_{i+1:03d}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            print(f"Downloading {url} -> {p}")
            r = requests.get(url, timeout=15)
            p.write_bytes(r.content)

    print("Download complete.")


def generate_from_images(images_dir: Path, out_file: Path):
    records = []

    distress_dir = images_dir / "distress"
    safe_dir = images_dir / "safe"

    for img_path in sorted(distress_dir.glob("*.jpg")) + sorted(distress_dir.glob("*.png")):
        b64 = encode_image(img_path)
        records.append(make_record(b64, "DISTRESS"))

    for img_path in sorted(safe_dir.glob("*.jpg")) + sorted(safe_dir.glob("*.png")):
        b64 = encode_image(img_path)
        records.append(make_record(b64, "SAFE"))

    print(f"Built {len(records)} records ({len(records)//2} distress + {len(records)//2} safe estimated)")
    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Saved to {out_file}")


def generate_synthetic(out_file: Path):
    """
    Generate a small synthetic JSONL using public image URLs (no local download).
    These are used for quick testing / CI. Real fine-tuning needs real images.
    """
    records = []

    for i, url in enumerate(DISTRESS_URLS):
        content = [
            {"type": "text", "text": USER_PROMPT},
            {"type": "image_url", "image_url": {"url": url}},
        ]
        records.append({
            "messages": [
                {"role": "user", "content": content},
                {"role": "assistant", "content": "DISTRESS"},
            ]
        })

    for i, url in enumerate(SAFE_URLS):
        content = [
            {"type": "text", "text": USER_PROMPT},
            {"type": "image_url", "image_url": {"url": url}},
        ]
        records.append({
            "messages": [
                {"role": "user", "content": content},
                {"role": "assistant", "content": "SAFE"},
            ]
        })

    print(f"Generated {len(records)} synthetic records")
    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"Saved to {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="Download sample images first")
    parser.add_argument("--synthetic", action="store_true", help="Generate synthetic JSONL (URL-based, no local images)")
    parser.add_argument("--images-dir", default="images", help="Directory with distress/ and safe/ subdirs")
    parser.add_argument("--out", default="helpstroll_dataset.jsonl", help="Output JSONL file")
    args = parser.parse_args()

    here = Path(__file__).parent
    out_file = here / args.out

    if args.synthetic:
        generate_synthetic(out_file)
    else:
        images_dir = here / args.images_dir
        if args.download:
            download_images(images_dir)
        if not images_dir.exists():
            print(f"Images dir not found: {images_dir}")
            print("Run with --download to fetch sample images, or --synthetic for URL-based records")
            sys.exit(1)
        generate_from_images(images_dir, out_file)
