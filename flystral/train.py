"""
Flystral fine-tuning script.
Fine-tunes Ministral 3B via the Mistral Fine-tuning API for vision-to-velocity output.

The fine-tuned model takes a drone camera image and outputs body-frame velocity vectors
{vx, vy, vz, yaw_rate} trained on 10,000 AirSim drone flight recordings. This approach
preserves the continuous nature of the flight control data rather than discretizing it.

Model choice: Ministral 3B chosen over Pixtral 12B for Flystral because drone flight
control requires sub-second response times. The 3B model runs ~4x faster at inference,
critical for real-time obstacle avoidance at 1-5 second intervals. Pixtral 12B is
reserved for Helpstral where accuracy on safety classification outweighs latency.

Usage:
  python train.py --dataset dataset/flystral_dataset.jsonl
  python train.py --dataset dataset/flystral_dataset.jsonl --model ministral-3b-latest --steps 500
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import MISTRAL_API_KEY

if not MISTRAL_API_KEY:
    print("Set MISTRAL_API_KEY in .env first", file=sys.stderr)
    sys.exit(1)

DEFAULT_MODEL = "ministral-3b-latest"


def run(dataset_path: Path, model: str, steps: int, lr: float):
    from mistralai import Mistral
    client = Mistral(api_key=MISTRAL_API_KEY)

    dataset_size = sum(1 for _ in open(dataset_path))
    file_size_mb = dataset_path.stat().st_size / (1024 * 1024)
    print(f"Dataset: {dataset_path}")
    print(f"  Records: {dataset_size}")
    print(f"  Size: {file_size_mb:.1f} MB")
    print(f"  Base model: {model}")
    print(f"  Training steps: {steps}")
    print(f"  Learning rate: {lr}")

    print(f"\nUploading dataset...")
    with open(dataset_path, "rb") as f:
        uploaded = client.files.upload(
            file={"file_name": dataset_path.name, "content": f},
            purpose="fine-tune",
        )
    file_id = uploaded.id
    print(f"  Uploaded file ID: {file_id}")

    print("Creating Flystral fine-tuning job...")
    job = client.fine_tuning.jobs.create(
        model=model,
        training_files=[{"file_id": file_id, "weight": 1}],
        hyperparameters={
            "training_steps": steps,
            "learning_rate": lr,
        },
        suffix="flystral",
        auto_start=True,
    )
    job_id = job.id
    print(f"  Job ID: {job_id}")
    print(f"  Created at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    print("\nPolling for completion...")
    start_time = time.time()
    while True:
        status = client.fine_tuning.jobs.get(job_id=job_id)
        elapsed = int(time.time() - start_time)
        print(f"  [{elapsed}s] Status: {status.status}")
        if status.status in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(30)

    if status.status != "succeeded":
        print(f"Job failed: {status.status}", file=sys.stderr)
        sys.exit(1)

    model_id = status.fine_tuned_model
    total_time = int(time.time() - start_time)
    print(f"\n{'='*60}")
    print(f"TRAINING COMPLETE")
    print(f"  Fine-tuned model ID: {model_id}")
    print(f"  Base model: {model}")
    print(f"  Dataset: {dataset_size} records ({file_size_mb:.1f} MB)")
    print(f"  Training steps: {steps}")
    print(f"  Training time: {total_time}s ({total_time//60}m {total_time%60}s)")
    print(f"{'='*60}")

    env_file = Path(__file__).parent.parent / ".env"
    with open(env_file, "a") as f:
        f.write(f"\nFLYSTRAL_MODEL_ID={model_id}\n")
    print(f"Model ID saved to {env_file}")

    training_log = {
        "model_id": model_id,
        "base_model": model,
        "dataset_records": dataset_size,
        "dataset_size_mb": round(file_size_mb, 1),
        "training_steps": steps,
        "learning_rate": lr,
        "training_time_s": total_time,
        "job_id": job_id,
        "file_id": file_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    log_path = Path(__file__).parent / "training_log.json"
    with open(log_path, "w") as f:
        json.dump(training_log, f, indent=2)
    print(f"Training log saved to {log_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset/flystral_dataset.jsonl")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Base model ID")
    parser.add_argument("--steps", type=int, default=300, help="Training steps")
    parser.add_argument("--lr", type=float, default=1e-4)
    args = parser.parse_args()

    here = Path(__file__).parent
    dataset_path = here / args.dataset

    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}")
        print("Generate it first: python dataset/from_public_drone_dataset.py")
        sys.exit(1)

    run(dataset_path, args.model, args.steps, args.lr)
