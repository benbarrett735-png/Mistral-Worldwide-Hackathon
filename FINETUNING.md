# Fine-Tuning

Both Flystral and Helpstral are fine-tuned versions of Mistral vision models using LoRA (PEFT) on Google Colab.

## Flystral — `BenBarr/flystral`

**Base model:** `mistralai/Ministral-3-3B-Instruct-2512-BF16`

Fine-tuned for real-time drone flight telemetry prediction from camera images.

| Parameter | Value |
|-----------|-------|
| Method | LoRA (PEFT) |
| LoRA rank | 4 |
| LoRA alpha | 8 |
| Target modules | `q_proj`, `v_proj` |
| Training steps | 500 |
| Learning rate | 2e-4 |
| Gradient accumulation | 8 |
| Dataset | [AirSim RGB+Depth 10K](https://www.kaggle.com/datasets/lukpellant/droneflight-obs-avoidanceairsimrgbdepth10k-320x320) (1,000 frames) |
| Hardware | Google Colab T4 GPU |

- **Training notebook:** [`flystral/train_colab.ipynb`](flystral/train_colab.ipynb)
- **Inference server:** [`flystral/serve_colab.ipynb`](flystral/serve_colab.ipynb)
- **HuggingFace:** [BenBarr/flystral](https://huggingface.co/BenBarr/flystral)

## Helpstral

Fine-tuned for pedestrian safety classification (SAFE / DISTRESS) from drone camera images.

Details and HuggingFace link coming soon.

## How inference works

The fine-tuned models are served from Google Colab via ngrok. Set the endpoint URLs in `.env`:

```
FLYSTRAL_ENDPOINT=https://your-ngrok-url.ngrok-free.dev
HELPSTRAL_ENDPOINT=https://your-ngrok-url.ngrok-free.dev
```

When the endpoint is available, the agent uses the fine-tuned model. When it's not, it falls back to the base Mistral model via the API.
