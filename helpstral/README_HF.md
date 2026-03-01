---
library_name: transformers
tags:
  - lora
  - peft
  - vision
  - safety
  - drone
  - pixtral
  - unsloth
base_model: unsloth/pixtral-12b-2409-bnb-4bit
license: apache-2.0
pipeline_tag: image-text-to-text
---

# Helpstral — LoRA Fine-tuned Pixtral 12B for Drone Safety Assessment

LoRA adapter for real-time pedestrian safety classification from drone camera images, built for the [Louise AI Safety Drone Escort](https://github.com/benbarrett735-png/Mistral-Worldwide-Hackathon) system.

## What it does

Given a drone camera frame during an escort mission, the model outputs a structured threat assessment:

- **threat_level** (1–10) — evidence-based risk score
- **status** — SAFE, CAUTION, or DISTRESS
- **people_count** — number of people visible in frame
- **user_moving** — whether the escorted person appears to be walking
- **proximity_alert** — whether another person is within ~3m of the user
- **observations** — what the model sees (lighting, obstacles, people)
- **pattern** — temporal reasoning from multi-frame context
- **reasoning** — explanation connecting image + location data
- **action** — CONTINUE_MONITORING, INCREASE_SCAN_RATE, ALERT_USER, EMERGENCY_HOVER, etc.

This powers operator-in-the-loop alerts: when the user stops moving for 10+ seconds or another person is in close proximity, mission control receives a review request.

## Training

| Parameter | Value |
|-----------|-------|
| Base model | Pixtral 12B (Unsloth 4-bit) |
| Method | LoRA (PEFT), trained with Unsloth |
| LoRA rank (r) | 64 |
| LoRA alpha | 128 |
| Target modules | language model attention (q_proj, v_proj, etc.) |
| Task type | CAUSAL_LM |
| PEFT version | 0.18.1 |

## Usage

**Inference server (Colab):** See [`helpstral/serve_colab.ipynb`](https://github.com/benbarrett735-png/Mistral-Worldwide-Hackathon/blob/main/helpstral/serve_colab.ipynb) in the Louise repo. Run it on a T4 GPU, then set `HELPSTRAL_ENDPOINT=<ngrok_url>` in `.env`.

**Load locally:**

```python
import torch
from transformers import AutoProcessor, LlavaForConditionalGeneration, BitsAndBytesConfig
from peft import PeftModel
from PIL import Image

processor = AutoProcessor.from_pretrained("mistral-community/pixtral-12b")
model = LlavaForConditionalGeneration.from_pretrained(
    "mistral-community/pixtral-12b",
    quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16),
    device_map="auto",
)
model = PeftModel.from_pretrained(model, "BenBarr/helpstral")
model = model.merge_and_unload().eval()

img = Image.open("drone_frame.jpg").convert("RGB")
chat = [{"role": "user", "content": [
    {"type": "image"},
    {"type": "text", "text": "Analyze this drone camera frame. Output JSON: threat_level, status, people_count, user_moving, proximity_alert, observations, pattern, reasoning, action."},
]}]
prompt = processor.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
inputs = processor(text=prompt, images=[img], return_tensors="pt").to(model.device)

with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=400, do_sample=False)

result = processor.batch_decode(out, skip_special_tokens=True)[0]
# Parse JSON from result...
```

## Architecture

Helpstral sits in the Louise multi-agent drone escort system:

- **Helpstral** (this model) — safety/threat assessment from camera images
- **Flystral** — flight control from camera images ([BenBarr/flystral](https://huggingface.co/BenBarr/flystral))
- **Louise** — conversational safety companion (Ministral 3B)

When `HELPSTRAL_ENDPOINT` is set, Helpstral uses this adapter exclusively. No base-model fallback — the fine-tuned endpoint is required.

## Developed by

Ben Barrett — Mistral Worldwide Hackathon 2026
