# Fine-Tuning

## Flystral — [`BenBarr/flystral`](https://huggingface.co/BenBarr/flystral)

LoRA fine-tuned Ministral 3B for real-time drone flight telemetry prediction from camera images.

**Base model:** `mistralai/Ministral-3-3B-Instruct-2512-BF16`

| Parameter | Value |
|-----------|-------|
| Method | LoRA (PEFT) |
| LoRA rank | 4 |
| LoRA alpha | 8 |
| Target modules | `q_proj`, `v_proj` |
| Training steps | 500 |
| Learning rate | 2e-4 |
| Gradient accumulation | 8 |
| Grad clipping | 0.3 |
| Precision | bfloat16 |
| Hardware | Google Colab T4 GPU |
| Training time | ~35 minutes |
| Dataset | [AirSim Drone Flight 10K](https://www.kaggle.com/datasets/lukpellant/droneflight-obs-avoidanceairsimrgbdepth10k-320x320) — 1,000 RGB frames with paired telemetry |

### Training log

```
[1] GPU: 0.00 GB
[2] Loading model...
    GPU: 6.14 GB
    169 image tokens
[3] Applying LoRA...
    trainable params: 262,144 || all params: 3,737,571,328 || trainable%: 0.0070
[4] Loading dataset...
    Done: 1000 examples
    Telemetry token count (sample): 148 tokens
[5] Dry run...
    embeds=[1, 185] GPU=6.41 GB
    Forward OK  loss=11.2381 GPU=7.89 GB
    Backward OK  GPU=8.12 GB
    Cleanup GPU=6.41 GB
[6] Training...
    Step  64/500  loss=10.6414  GPU=8.14 GB
    Step 128/500  loss=9.5537   GPU=8.14 GB
    Step 192/500  loss=7.0885   GPU=8.14 GB
    Step 256/500  loss=4.6498   GPU=8.14 GB
    Step 320/500  loss=3.1225   GPU=8.14 GB
    Step 384/500  loss=2.4410   GPU=8.14 GB
    Step 448/500  loss=1.9873   GPU=8.14 GB
    Step 500/500  loss=1.7251   GPU=8.14 GB
    Training complete!
[7] Saving...
    Saved to ./ministral-drone-final/
```

Loss decreased from 10.6 → 1.7 over 500 steps (6.2× reduction), confirming the adapter learned to map drone camera frames to telemetry vectors.

### Artefacts

| Artefact | Location |
|----------|----------|
| LoRA adapter weights | [HuggingFace: BenBarr/flystral](https://huggingface.co/BenBarr/flystral) |
| `adapter_config.json` | [`flystral/ministral-drone-final/adapter_config.json`](flystral/ministral-drone-final/adapter_config.json) |
| `adapter_model.safetensors` | 6.2 MB — LoRA weight delta |
| Training notebook | [`flystral/train_colab.ipynb`](flystral/train_colab.ipynb) |
| Inference server | [`flystral/serve_colab.ipynb`](flystral/serve_colab.ipynb) |

### Design decisions

**Why Ministral 3B (not Pixtral 12B)?** Flight control requires sub-second inference at 1–5s frame intervals. Ministral 3B runs ~4× faster than Pixtral 12B on a T4 GPU. Pixtral 12B is reserved for Helpstral (safety classification) where accuracy outweighs latency.

**Why LoRA r=4?** Telemetry prediction is a narrow task — mapping visual features to a fixed-length numeric vector. A small adapter (262K trainable params out of 3.7B) is sufficient and keeps inference fast. Higher ranks showed diminishing returns in early experiments.

**Why 1,000 frames (not 10,000)?** Colab T4 memory constrains batch processing. 1,000 frames with gradient accumulation 8 gives 62 effective updates over 500 steps — enough to converge for this task.

### How inference works

The fine-tuned model is served from a Colab GPU via ngrok/cloudflare tunnel:

```
FLYSTRAL_ENDPOINT=https://your-tunnel-url
```

When the endpoint is available, `flystral/agent.py` sends camera frames to the fine-tuned model and receives velocity vectors (`vx`, `vy`, `vz`, `yaw_rate`). When the endpoint is offline, it falls back to agentic mode on the base Ministral 3B via the Mistral API — still functional with tool calling, just without the fine-tuned telemetry prediction.

---

## Helpstral

Helpstral uses Pixtral 12B (`pixtral-12b-2409`) via the Mistral API for vision-based safety assessment. It analyses drone camera frames for threats and outputs structured assessments including threat level, people count, proximity alerts, and recommended actions.

Helpstral is not fine-tuned — it uses advanced prompting with Mistral's function calling API to query real OpenStreetMap data (streetlight density, lit road ratio, POI density) and cross-reference with a temporal memory window of past assessments. The combination of real geo-intelligence data and multi-frame temporal reasoning gives strong safety classification without requiring a fine-tuned model.

---

## Louise

Louise uses Ministral 3B (`ministral-3b-latest`) via the Mistral API as a conversational safety companion. It provides contextual safety information using real geo-intelligence data through four function-calling tools. No fine-tuning — the base model's instruction-following capability is sufficient for this conversational role.
