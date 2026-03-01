# Helpstral LoRA Adapter — Pixtral 12B

LoRA adapter configuration for [BenBarr/helpstral](https://huggingface.co/BenBarr/helpstral) — fine-tuned Pixtral 12B for structured safety assessment from drone camera images.

## Configuration

| Parameter | Value |
|-----------|-------|
| Base model | `unsloth/pixtral-12b-2409-bnb-4bit` |
| PEFT type | LoRA |
| LoRA rank (r) | 64 |
| LoRA alpha | 128 |
| LoRA dropout | 0.05 |
| Target modules | `q_proj`, `v_proj`, `k_proj`, `o_proj`, `gate_proj`, `down_proj`, `up_proj` |
| Task type | CAUSAL_LM |
| PEFT version | 0.18.1 |

Higher rank (64 vs Flystral's 4) is appropriate because safety assessment is a nuanced reasoning task — Helpstral must classify threat level, count people, detect motion, identify proximity, and produce multi-sentence structured reasoning from a single drone frame. Flystral predicts a narrow telemetry vector; Helpstral reasons about human safety.

## Artefacts

| Artefact | Location |
|----------|----------|
| LoRA adapter weights | [HuggingFace: BenBarr/helpstral](https://huggingface.co/BenBarr/helpstral) |
| `adapter_config.json` | This directory |
| `adapter_model.safetensors` | HuggingFace only (Pixtral 12B adapter is ~200MB) |
| Inference server | [`helpstral/serve_colab.ipynb`](../serve_colab.ipynb) |

## Output schema

Helpstral outputs a JSON object on every camera frame:

```json
{
  "threat_level": 3,
  "status": "SAFE",
  "people_count": 1,
  "user_moving": true,
  "proximity_alert": false,
  "observations": ["well-lit street", "user walking steadily", "no followers visible"],
  "pattern": "Consistent safe — no changes across last 3 frames",
  "reasoning": "Street has adequate lighting and no other pedestrians. User motion is steady and directional. No threat indicators in frame or recent history.",
  "action": "CONTINUE_MONITORING"
}
```

This structured output drives:
- Flystral's altitude and speed decisions
- Operator review triggers (`people_count`, `proximity_alert`, `user_moving`)
- Auto-escalation when `threat_level >= 6` persists across 3+ frames
