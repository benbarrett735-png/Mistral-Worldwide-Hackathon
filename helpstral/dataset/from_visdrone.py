"""
Build Helpstral dataset (SAFE / DISTRESS) from VisDrone imagery.

Uses the same VisDrone2019-DET source as Flystral. Labels:
  - Pedestrian or people in frame -> SAFE (person visible, escort context)
  - No person / empty / unclear -> DISTRESS (flag for review)

Run from this directory (FiftyOne + VisDrone already installed):
  python from_visdrone.py --max-samples 400 --out helpstral_dataset.jsonl
"""

import argparse
import base64
import json
import sys
from pathlib import Path

PEDESTRIAN_LABELS = {"pedestrian", "people"}


def load_visdrone(max_samples: int = 500):
    try:
        import fiftyone.utils.huggingface as fouh
    except ImportError:
        print("Install FiftyOne: pip install fiftyone", file=sys.stderr)
        sys.exit(1)

    print("Loading VisDrone2019-DET from Hugging Face...")
    dataset = fouh.load_from_hub("Voxel51/VisDrone2019-DET", max_samples=max_samples)
    samples = list(dataset.iter_samples(autosave=False))
    out = []
    for s in samples:
        filepath = s.filepath
        if not filepath or not Path(filepath).exists():
            continue
        dets = s.ground_truth
        labels = []
        if dets and hasattr(dets, "detections"):
            for d in dets.detections:
                lbl = getattr(d, "label", None) or getattr(d, "label_id", None)
                if lbl is not None:
                    labels.append(str(lbl).lower())
        out.append((filepath, labels))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-samples", type=int, default=400)
    parser.add_argument("--out", default="helpstral_dataset.jsonl")
    args = parser.parse_args()

    here = Path(__file__).parent
    out_file = here / args.out

    USER_PROMPT = (
        "Analyze this image. Is the person in danger or distress? "
        "Respond with exactly one word: DISTRESS or SAFE."
    )

    samples = load_visdrone(max_samples=args.max_samples)
    print(f"Loaded {len(samples)} samples")

    records = []
    for path, labels in samples:
        if not Path(path).exists():
            continue
        has_person = any(l in PEDESTRIAN_LABELS for l in labels)
        label = "SAFE" if has_person else "DISTRESS"
        b64 = base64.b64encode(Path(path).read_bytes()).decode()
        content = [
            {"type": "text", "text": USER_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]
        records.append({
            "messages": [
                {"role": "user", "content": content},
                {"role": "assistant", "content": label},
            ]
        })

    with open(out_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    n_safe = sum(1 for r in records if r["messages"][1]["content"] == "SAFE")
    n_distress = len(records) - n_safe
    print(f"Wrote {len(records)} records to {out_file} (SAFE: {n_safe}, DISTRESS: {n_distress})")
    print("Train with: cd .. && python train.py --dataset dataset/helpstral_dataset.jsonl")


if __name__ == "__main__":
    main()
