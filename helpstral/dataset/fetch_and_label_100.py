"""
Fetch ~100 images per label (SAFE and DISTRESS) and build helpstral_dataset.jsonl.

Uses Pexels API (free key at https://www.pexels.com/api/) to search and download.
You set PEXELS_API_KEY in .env or environment; then run:

  python fetch_and_label_100.py --target 100

This will:
  1. Download up to 100 SAFE images (person walking, well-lit street, etc.)
  2. Download up to 100 DISTRESS images (dark alley, person running, night street, etc.)
  3. Save them to images/safe/ and images/distress/
  4. Build dataset/helpstral_dataset.jsonl for fine-tuning

Requirements: pip install requests python-dotenv
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add project root for dotenv
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

# Pexels search queries: (query, label). We'll fetch up to target per label.
SAFE_QUERIES = [
    "person walking street",
    "person walking sidewalk",
    "pedestrian daytime",
    "well lit street walking",
    "person walking park",
    "street scene daytime",
    "person walking city",
]

DISTRESS_QUERIES = [
    "dark alley night",
    "person running street night",
    "empty street night",
    "dark street lonely",
    "person sitting ground street",
    "shadow alley",
    "night street empty",
]


def fetch_pexels_urls(api_key: str, query: str, per_page: int = 80, max_photos: int = 100) -> list[str]:
    """Return list of image URLs from Pexels search (medium size)."""
    import requests
    urls = []
    page = 1
    while len(urls) < max_photos:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": per_page, "page": page},
            headers={"Authorization": api_key},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Pexels API error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        photos = data.get("photos") or []
        if not photos:
            break
        for p in photos:
            # Prefer 'medium' or 'large' for decent resolution
            src = p.get("src") or {}
            url = src.get("medium") or src.get("large") or src.get("original")
            if url and url not in urls:
                urls.append(url)
                if len(urls) >= max_photos:
                    return urls
        page += 1
        time.sleep(0.3)  # be nice to API
    return urls


def download_images(urls: list[str], out_dir: Path, prefix: str) -> list[Path]:
    """Download URLs to out_dir/prefix_001.jpg etc. Return paths."""
    import requests
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, url in enumerate(urls):
        path = out_dir / f"{prefix}_{i+1:03d}.jpg"
        if path.exists():
            paths.append(path)
            continue
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            path.write_bytes(r.content)
            paths.append(path)
        except Exception as e:
            print(f"  Skip {url[:50]}...: {e}", file=sys.stderr)
        time.sleep(0.1)
    return paths


def main():
    parser = argparse.ArgumentParser(description="Fetch ~100 images per label via Pexels and build JSONL")
    parser.add_argument("--target", type=int, default=100, help="Target number of images per label (default 100)")
    parser.add_argument("--images-dir", default="images", help="Directory to save images (safe/ and distress/)")
    parser.add_argument("--out", default="helpstral_dataset.jsonl", help="Output JSONL path")
    parser.add_argument("--skip-download", action="store_true", help="Only build JSONL from existing images")
    args = parser.parse_args()

    here = Path(__file__).parent
    images_dir = here / args.images_dir
    out_file = here / args.out

    safe_dir = images_dir / "safe"
    distress_dir = images_dir / "distress"

    if not args.skip_download:
        api_key = os.environ.get("PEXELS_API_KEY", "").strip()
        if not api_key:
            print("Set PEXELS_API_KEY in .env (get a free key at https://www.pexels.com/api/)", file=sys.stderr)
            sys.exit(1)

        print(f"Fetching up to {args.target} SAFE images from Pexels...")
        safe_urls = []
        for q in SAFE_QUERIES:
            safe_urls.extend(fetch_pexels_urls(api_key, q, max_photos=args.target))
            safe_urls = list(dict.fromkeys(safe_urls))[: args.target]
            if len(safe_urls) >= args.target:
                break
        safe_urls = safe_urls[: args.target]
        print(f"  Got {len(safe_urls)} URLs, downloading...")
        download_images(safe_urls, safe_dir, "safe")

        print(f"Fetching up to {args.target} DISTRESS images from Pexels...")
        distress_urls = []
        for q in DISTRESS_QUERIES:
            distress_urls.extend(fetch_pexels_urls(api_key, q, max_photos=args.target))
            distress_urls = list(dict.fromkeys(distress_urls))[: args.target]
            if len(distress_urls) >= args.target:
                break
        distress_urls = distress_urls[: args.target]
        print(f"  Got {len(distress_urls)} URLs, downloading...")
        download_images(distress_urls, distress_dir, "distress")

    # Build JSONL using existing generate_dataset logic
    sys.path.insert(0, str(here))
    from generate_dataset import encode_image, make_record

    records = []
    for img_path in sorted(safe_dir.glob("*.jpg")) + sorted(safe_dir.glob("*.png")):
        b64 = encode_image(img_path)
        records.append(make_record(b64, "SAFE"))
    for img_path in sorted(distress_dir.glob("*.jpg")) + sorted(distress_dir.glob("*.png")):
        b64 = encode_image(img_path)
        records.append(make_record(b64, "DISTRESS"))

    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    n_safe = sum(1 for r in records if r["messages"][1]["content"] == "SAFE")
    n_distress = len(records) - n_safe
    print(f"Saved {len(records)} records ({n_safe} SAFE, {n_distress} DISTRESS) to {out_file}")
    print("Run: python train.py --dataset dataset/helpstral_dataset.jsonl")


if __name__ == "__main__":
    main()
