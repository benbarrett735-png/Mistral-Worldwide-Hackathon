"""
Import lots of drone imagery that shows people (relevant to escort/safety use case).

Uses Pexels API only – no FiftyOne, minimal disk. Fetches images for queries like:
  "drone view person", "aerial pedestrian", "drone person walking", "aerial view people street"
then builds flystral_dataset.jsonl (and optionally helpstral) with heuristic labels.

Usage:
  Set PEXELS_API_KEY in .env, then:
  python load_drone_imagery_people.py --target 200

Requirements: pip install requests python-dotenv
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

# Queries focused on drone/aerial imagery WITH people (escort-relevant).
DRONE_PEOPLE_QUERIES = [
    "drone view person walking",
    "aerial view pedestrian street",
    "drone footage person",
    "aerial view people street",
    "drone camera person",
    "top down view person walking",
    "aerial pedestrian crossing",
    "drone view people city",
    "bird eye view person street",
    "aerial view person road",
    "drone surveillance person",
    "overhead view pedestrian",
    "uav view person",
    "drone follow person",
]

# We assign a Flystral command per query batch so we get variety (not all FOLLOW).
QUERY_TO_COMMAND = [
    ("drone view person walking", "FOLLOW", "0.7"),
    ("aerial view pedestrian street", "FOLLOW", "0.6"),
    ("drone footage person", "FOLLOW", "0.5"),
    ("aerial view people street", "HOVER", "2"),   # multiple people
    ("drone camera person", "FOLLOW", "0.6"),
    ("top down view person walking", "FOLLOW", "0.7"),
    ("aerial pedestrian crossing", "HOVER", "3"),
    ("drone view people city", "FOLLOW", "0.5"),
    ("bird eye view person street", "FOLLOW", "0.6"),
    ("aerial view person road", "FOLLOW", "0.7"),
    ("drone surveillance person", "FOLLOW", "0.5"),
    ("overhead view pedestrian", "FOLLOW", "0.6"),
    ("uav view person", "FOLLOW", "0.5"),
    ("drone follow person", "FOLLOW", "0.8"),
]


def fetch_pexels_urls(api_key: str, query: str, per_page: int = 80, max_photos: int = 50) -> list[str]:
    try:
        import requests
    except ImportError:
        raise RuntimeError("pip install requests")
    urls = []
    page = 1
    while len(urls) < max_photos:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": min(per_page, 80), "page": page},
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
            src = p.get("src") or {}
            url = src.get("medium") or src.get("large") or src.get("original")
            if url and url not in urls:
                urls.append(url)
                if len(urls) >= max_photos:
                    return urls
        page += 1
        time.sleep(0.35)
    return urls


def download_image(url: str, path: Path) -> bool:
    try:
        import requests
    except ImportError:
        return False
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        path.write_bytes(r.content)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Import drone imagery of people via Pexels")
    parser.add_argument("--target", type=int, default=200, help="Target total images (spread across queries)")
    parser.add_argument("--out", default="flystral_dataset.jsonl", help="Output JSONL path")
    parser.add_argument("--images-dir", default="images_drone_people", help="Folder to save images")
    args = parser.parse_args()

    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        print("Set PEXELS_API_KEY in .env (free at https://www.pexels.com/api/)", file=sys.stderr)
        sys.exit(1)

    here = Path(__file__).parent
    images_dir = here / args.images_dir
    images_dir.mkdir(parents=True, exist_ok=True)
    out_file = here / args.out

    per_query = max(10, (args.target // len(QUERY_TO_COMMAND)) + 1)
    seen_urls = set()
    # (local_path, command, param)
    labeled = []

    for query, cmd, param in QUERY_TO_COMMAND:
        urls = fetch_pexels_urls(api_key, query, max_photos=per_query)
        for i, url in enumerate(urls):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            safe_name = f"{cmd}_{len(labeled):04d}.jpg"
            path = images_dir / safe_name
            if path.exists():
                labeled.append((path, cmd, param))
                continue
            if download_image(url, path):
                labeled.append((path, cmd, param))
            time.sleep(0.1)
        n_cmd = sum(1 for _, c, _ in labeled if c == cmd)
        print(f"  {query[:42]:42s} -> {cmd}|{param} ({n_cmd} images)")

    USER_PROMPT = (
        "You are Flystral, a drone autopilot AI. "
        "Analyze this drone camera image and output exactly one command from:\n"
        "FOLLOW|<speed 0.1-1.0>, AVOID_LEFT|<dist_m>, AVOID_RIGHT|<dist_m>, "
        "CLIMB|<meters>, HOVER|<seconds>, REPLAN|0, DESCEND|<meters>\n"
        "Respond with the command only. Example: FOLLOW|0.7"
    )

    records = []
    for path, cmd, param in labeled:
        if not path.exists():
            continue
        b64 = base64.b64encode(path.read_bytes()).decode()
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
    print(f"\nSaved {len(records)} drone imagery (people) records to {out_file}")
    for cmd, n in sorted(counts.items()):
        print(f"  {cmd}: {n}")
    print("Train with: python train.py --dataset dataset/flystral_dataset.jsonl")


if __name__ == "__main__":
    main()
