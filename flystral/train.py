"""
Flystral fine-tuning script.
Fine-tunes Pixtral 12B via the Mistral Fine-tuning API for vision-to-command output.

Usage:
  python train.py --dataset dataset/flystral_dataset.jsonl
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MISTRAL_API_KEY

if not MISTRAL_API_KEY:
    print("Set MISTRAL_API_KEY in .env first", file=sys.stderr)
    sys.exit(1)


def run(dataset_path: Path, epochs: int, lr: float):
    from mistralai import Mistral
    client = Mistral(api_key=MISTRAL_API_KEY)

    print(f"Uploading dataset: {dataset_path}")
    with open(dataset_path, "rb") as f:
        uploaded = client.files.upload(
            file={"file_name": dataset_path.name, "content": f},
            purpose="fine-tune",
        )
    file_id = uploaded.id
    print(f"  Uploaded file ID: {file_id}")

    print("Creating Flystral fine-tuning job...")
    job = client.fine_tuning.jobs.create(
        model="pixtral-12b-latest",  # vision model for image → flight commands
        training_files=[{"file_id": file_id, "weight": 1}],
        hyperparameters={
            "training_steps": epochs * 60,
            "learning_rate": lr,
        },
        suffix="flystral",
        auto_start=True,
    )
    job_id = job.id
    print(f"  Job ID: {job_id}")

    print("Polling for completion...")
    while True:
        status = client.fine_tuning.jobs.get(job_id=job_id)
        print(f"  Status: {status.status}")
        if status.status in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(30)

    if status.status != "succeeded":
        print(f"Job failed: {status.status}", file=sys.stderr)
        sys.exit(1)

    model_id = status.fine_tuned_model
    print(f"\nFine-tuned model: {model_id}")

    env_file = Path(__file__).parent.parent / ".env"
    with open(env_file, "a") as f:
        f.write(f"\nFLYSTRAL_MODEL_ID={model_id}\n")
    print(f"Model ID saved to {env_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset/flystral_dataset.jsonl")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--lr", type=float, default=1e-4)
    args = parser.parse_args()

    here = Path(__file__).parent
    dataset_path = here / args.dataset

    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}")
        print("Run: python dataset/generate_dataset.py --synthetic")
        sys.exit(1)

    run(dataset_path, args.epochs, args.lr)
