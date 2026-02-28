"""
Fetch ~100 images per command (or ~15 per command to total 100+) and build flystral_dataset.jsonl.

Uses Pexels API (free key at https://www.pexels.com/api/). Run:

  python fetch_and_label_100.py --target 15

Target 15 per command → 7 commands = 105 images. Use --target 100 for 100 per command (700 images).

  1. Downloads aerial/street/drone-style images for each command (FOLLOW, AVOID_LEFT, etc.)
  2. Saves to images/follow/, images/avoid_left/, etc.
  3. Builds dataset/flystral_dataset.jsonl

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

# (Pexels search query, command, param). Multiple queries per command to get enough variety.
COMMAND_QUERIES = [
    # FOLLOW: clear aerial/street view
    ("aerial view street", "FOLLOW", "0.7"),
    ("drone view city street", "FOLLOW", "0.6"),
    ("top down road", "FOLLOW", "0.5"),
    ("aerial city daytime", "FOLLOW", "0.8"),
    ("bird eye view street", "FOLLOW", "0.6"),
    # AVOID_LEFT (obstacle right)
    ("aerial view road tree", "AVOID_LEFT", "2"),
    ("drone view street obstacle", "AVOID_LEFT", "3"),
    # AVOID_RIGHT
    ("aerial street building side", "AVOID_RIGHT", "2"),
    ("top down road vehicle", "AVOID_RIGHT", "2.5"),
    # CLIMB
    ("aerial view bridge", "CLIMB", "5"),
    ("drone building ahead", "CLIMB", "8"),
    ("aerial trees canopy", "CLIMB", "5"),
    # HOVER
    ("aerial view fog", "HOVER", "3"),
    ("drone view blur", "HOVER", "5"),
    ("aerial park empty", "HOVER", "4"),
    # REPLAN
    ("aerial intersection", "REPLAN", "0"),
    ("drone view crossroads", "REPLAN", "0"),
    # DESCEND
    ("aerial view high altitude", "DESCEND", "5"),
    ("drone view from above", "DESCEND", "3"),
]


def fetch_pexels_urls(api_key: str, query: str, per_page: int = 80, max_photos: int = 30) -> list[str]:
    import requests
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
        time.sleep(0.3)
    return urls


def download_images(urls: list[str], out_dir: Path, prefix: str) -> list[Path]:
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=15, help="Target images per command (default 15 → ~105 total)")
    parser.add_argument("--images-dir", default="images", help="Base dir for command subdirs")
    parser.add_argument("--out", default="flystral_dataset.jsonl", help="Output JSONL")
    parser.add_argument("--skip-download", action="store_true", help="Only build JSONL from existing images")
    args = parser.parse_args()

    here = Path(__file__).parent
    images_dir = here / args.images_dir
    out_file = here / args.out

    # Folder name from command: FOLLOW -> follow, AVOID_LEFT -> avoid_left
    def cmd_to_folder(cmd: str) -> str:
        return cmd.lower()

    USER_PROMPT = (
        "You are Flystral, a drone autopilot AI. "
        "Analyze this drone camera image and output exactly one command from:\n"
        "FOLLOW|<speed 0.1-1.0>, AVOID_LEFT|<dist_m>, AVOID_RIGHT|<dist_m>, "
        "CLIMB|<meters>, HOVER|<seconds>, REPLAN|0, DESCEND|<meters>\n"
        "Respond with the command only. Example: FOLLOW|0.7"
    )

    if not args.skip_download:
        api_key = os.environ.get("PEXELS_API_KEY", "").strip()
        if not api_key:
            print("Set PEXELS_API_KEY in .env (get free key at https://www.pexels.com/api/)", file=sys.stderr)
            sys.exit(1)

        # Collect URLs per command (one folder per command)
        from collections import defaultdict
        by_cmd = defaultdict(list)  # cmd -> list of urls
        for query, cmd, param in COMMAND_QUERIES:
            if len(by_cmd[cmd]) >= args.target:
                continue
            urls = fetch_pexels_urls(api_key, query, max_photos=args.target)
            for u in urls:
                if u not in by_cmd[cmd]:
                    by_cmd[cmd].append(u)
                if len(by_cmd[cmd]) >= args.target:
                    break
            time.sleep(0.5)

        for cmd, urls in by_cmd.items():
            folder = cmd_to_folder(cmd)
            out_dir = images_dir / folder
            print(f"Downloading {len(urls)} images for {cmd}...")
            download_images(urls[: args.target], out_dir, folder)

    # Build JSONL from images in images/<command>/
    FOLDER_COMMANDS = {
        "follow": ("FOLLOW", "0.7"),
        "avoid_left": ("AVOID_LEFT", "2"),
        "avoid_right": ("AVOID_RIGHT", "2"),
        "climb": ("CLIMB", "5"),
        "hover": ("HOVER", "3"),
        "replan": ("REPLAN", "0"),
        "descend": ("DESCEND", "5"),
    }

    records = []
    for folder, (cmd, param) in FOLDER_COMMANDS.items():
        d = images_dir / folder
        if not d.exists():
            continue
        for img_path in sorted(d.glob("*.jpg")) + sorted(d.glob("*.png")):
            b64 = base64.b64encode(img_path.read_bytes()).decode()
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
    print(f"Saved {len(records)} records to {out_file}")
    for cmd, n in sorted(counts.items()):
        print(f"  {cmd}: {n}")
    print("Run: python train.py --dataset dataset/flystral_dataset.jsonl")


if __name__ == "__main__":
    main()
