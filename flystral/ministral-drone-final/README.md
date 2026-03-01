---
library_name: transformers
tags:
  - lora
  - peft
  - drone
  - telemetry
  - vision
  - mistral
  - ministral
base_model: mistralai/Ministral-3-3B-Instruct-2512-BF16
license: apache-2.0
pipeline_tag: image-text-to-text
---

# Flystral — LoRA Fine-tuned Ministral 3B for Drone Flight Control

LoRA adapter for real-time drone telemetry prediction from camera images, built for the [Louise AI Safety Drone Escort](https://github.com/BenBarr/louise) system.

## What it does

Given a drone camera frame, the model outputs a telemetry vector (velocity, orientation, altitude adjustments) that drives autonomous flight control. This enables the drone to react to visual obstacles and environmental conditions in real-time during pedestrian escort missions.

## Training

| Parameter | Value |
|-----------|-------|
| Base model | `mistralai/Ministral-3-3B-Instruct-2512-BF16` |
| Method | LoRA (PEFT) |
| LoRA rank (r) | 4 |
| LoRA alpha | 8 |
| Target modules | `q_proj`, `v_proj` |
| Task type | CAUSAL_LM |
| Steps | 500 |
| Learning rate | 2e-4 |
| Gradient accumulation | 8 |
| Grad clipping | 0.3 |
| Precision | bfloat16 |
| Hardware | Google Colab T4 GPU (15 GB VRAM) |
| Training time | ~35 minutes |
| PEFT version | 0.18.1 |

### Dataset

[AirSim RGB+Depth Drone Flight 10K](https://www.kaggle.com/datasets/lukpellant/droneflight-obs-avoidanceairsimrgbdepth10k-320x320) — 1,000 RGB frames (320×320) from Microsoft AirSim simulator, each paired with a numpy telemetry array containing velocity/orientation data.

Each training example pairs a drone camera image with a telemetry vector (50 float values) representing the drone's state. The model learns to predict these vectors from visual input.

### Training loss

```
Step  64/500  loss=10.6414
Step 128/500  loss=9.5537
Step 192/500  loss=7.0885
Step 256/500  loss=4.6498
Step 320/500  loss=3.1225
Step 384/500  loss=2.4410
Step 448/500  loss=1.9873
Step 500/500  loss=1.7251
```

Loss decreased from 10.6 → 1.7 over 500 steps, confirming the adapter learned to map visual features to telemetry predictions.

## Usage

```python
import torch
from transformers import AutoProcessor, Mistral3ForConditionalGeneration
from peft import PeftModel
from PIL import Image

processor = AutoProcessor.from_pretrained("mistralai/Ministral-3-3B-Instruct-2512-BF16")
model = Mistral3ForConditionalGeneration.from_pretrained(
    "mistralai/Ministral-3-3B-Instruct-2512-BF16",
    torch_dtype=torch.bfloat16,
)
model = PeftModel.from_pretrained(model, "BenBarr/flystral")
model = model.merge_and_unload().cuda().eval()

img = Image.open("drone_frame.jpg").convert("RGB")

messages = [{"role": "user", "content": [
    {"type": "image"},
    {"type": "text", "text": "Output the raw telemetry for this frame."},
]}]

text = processor.apply_chat_template(messages, add_generation_prompt=True)
inputs = processor(text=text, images=[img], return_tensors="pt").to("cuda")

with torch.no_grad():
    output_ids = model.generate(**inputs, max_new_tokens=200, do_sample=False)

result = processor.decode(output_ids[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
print(result)  # Telemetry vector: vx, vy, vz, yaw_rate, ...
```

## Architecture

The adapter sits in the Louise multi-agent drone escort system:

- **Flystral** (this model) — flight control from camera images
- **Helpstral** — safety/threat assessment from camera images (Pixtral 12B)
- **Louise** — conversational safety companion (Ministral 3B)

When the fine-tuned endpoint is available, Flystral uses this adapter. When offline, it falls back to agentic mode on the base Ministral 3B via the Mistral API with function calling.

## Developed by

Ben Barrett — Mistral Worldwide Hackathon 2026
