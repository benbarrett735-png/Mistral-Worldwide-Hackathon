# Mistral Fine-Tuning Guide — Louise / Hackathon

Quick reference for **which Mistral models exist**, **which you can fine-tune**, and **how to run fine-tuning** in this project.

---

## Our approach: two fine-tuning methods

We use **two complementary approaches** depending on the agent:

### Flystral — Local LoRA fine-tuning (Colab T4 GPU)

**Model:** `mistralai/Ministral-3-3B-Instruct-2512-BF16` with PEFT LoRA (r=4, α=8)

Flystral requires sub-second inference for real-time drone flight control. We fine-tuned Ministral 3B locally on Google Colab using a T4 GPU with LoRA adapters on the attention layers (`q_proj`, `v_proj`), keeping the vision tower frozen.

- **Dataset:** 1,000 AirSim drone flight frames from [Kaggle](https://www.kaggle.com/datasets/lukpellant/droneflight-obs-avoidanceairsimrgbdepth10k-320x320) — RGB images paired with telemetry vectors
- **Training:** 500 steps, AdamW lr=2e-4, gradient accumulation 8, gradient clipping 0.3, bfloat16
- **Output:** LoRA adapter weights in `flystral/ministral-drone-final/`
- **Notebook:** [`flystral/train_colab.ipynb`](flystral/train_colab.ipynb)

### Helpstral — Mistral API fine-tuning

**Model:** `pixtral-12b-latest` fine-tuned via the Mistral API

Helpstral prioritises accuracy over latency for safety classification (SAFE/DISTRESS). Fine-tuning runs on Mistral's servers — upload JSONL, get back a model ID.

- **Script:** `helpstral/train.py`
- **Notebook:** [`helpstral/train_colab.ipynb`](helpstral/train_colab.ipynb)
- **Output:** A `ft:pixtral-12b:...` model ID set in `.env` as `HELPSTRAL_MODEL_ID`

---

## All Mistral models you could use

### Fine-tunable via API

From [Text & Vision Fine-tuning](https://docs.mistral.ai/capabilities/finetuning/text_vision_finetuning):

| Base model ID | Type | Best for |
|---------------|------|----------|
| **pixtral-12b-latest** | Vision | Image → label or text (Helpstral). |
| **ministral-3b-latest** | Vision | Smaller/cheaper vision fine-tuning. |
| **ministral-8b-latest** | Vision | Mid-size vision. |
| **open-mistral-7b** | Text only | Text-only SFT, no images. |
| **mistral-small-latest** | Text only | Small text model. |
| **open-mistral-nemo** | Text only | 12B text-only. |
| **codestral-latest** | Text only | Code-focused. |
| **mistral-large-latest** | Text only | Largest text base in the fine-tune list. |

### Fine-tunable locally (HuggingFace + PEFT)

| HuggingFace model | Params | Notes |
|-------------------|--------|-------|
| **mistralai/Ministral-3-3B-Instruct-2512-BF16** | 3B | Vision + text. Used for Flystral LoRA. Fits on T4 with gradient checkpointing. |
| **mistralai/Ministral-8B-Instruct-2412** | 8B | Vision + text. Needs A100 or quantisation. |
| **mistralai/Pixtral-12B-2409** | 12B | Vision. Needs A100. |

### Full Mistral lineup (inference / context)

| Category | Model | API / notes |
|----------|--------|-------------|
| **Frontier generalist** | Mistral Large 3 | Open-weight, multimodal. |
| | Mistral Medium 3.1 | Premier, multimodal. |
| | Mistral Small 3.2 | Open, multimodal. |
| **Ministral (vision + text)** | Ministral 3 14B, 8B, 3B | Open; 3B/8B are fine-tunable. |
| **Reasoning** | Magistral Medium 1.2, Small 1.2 | Premier / open, multimodal reasoning. |
| **Vision (legacy)** | Pixtral 12B | Fine-tunable as `pixtral-12b-latest`. |
| | Pixtral Large | Premier, inference. |
| **Code** | Codestral | Premier; fine-tunable as `codestral-latest`. |
| | Devstral 2 | Open, code agents. |
| **Audio** | Voxtral Mini Transcribe | Premier / open, transcription. |
| **Other** | Mistral Nemo 12B | Open; fine-tunable as `open-mistral-nemo` (text only). |
| | Mistral 7B, Mixtral 8x7B / 8x22B | Open-weight; 7B fine-tunable as `open-mistral-7b`. |

---

## Flystral: LoRA fine-tuning details

### Why local LoRA instead of API?

Drone flight control outputs raw telemetry vectors (50 float values per frame). The Mistral API fine-tuning works well for classification/text tasks but local LoRA gives us:
- Direct control over training (gradient accumulation, custom loss masking)
- The ability to freeze the vision tower while training only attention layers
- A portable adapter we can deploy anywhere

### How to reproduce

1. Open [`flystral/train_colab.ipynb`](flystral/train_colab.ipynb) in Google Colab (T4 GPU)
2. Add your Kaggle credentials and HuggingFace token
3. Run all cells — training takes ~30-40 min
4. Download `ministral-drone-final.zip` and extract to `flystral/ministral-drone-final/`

### Architecture

```
Ministral 3B (frozen vision tower + frozen projector)
  └── LoRA adapters on q_proj, v_proj (r=4, α=8)
      └── Input: [BOS] [IMG_TOKENS] "Output the raw telemetry for this frame." [TELEMETRY] [EOS]
      └── Labels: masked on everything except telemetry tokens
```

### Training config

| Parameter | Value |
|-----------|-------|
| Base model | `Ministral-3-3B-Instruct-2512-BF16` |
| LoRA rank | 4 |
| LoRA alpha | 8 |
| Target modules | `q_proj`, `v_proj` |
| Image size | 128×128 |
| Steps | 500 |
| Batch size | 1 (grad accum 8) |
| Learning rate | 2e-4 |
| Gradient clipping | 0.3 |
| Precision | bfloat16 |
| GPU | T4 (15 GB) |

---

## Helpstral: API fine-tuning details

### How to run

```bash
cd helpstral
python dataset/generate_dataset.py --synthetic
python train.py --dataset dataset/helpstral_dataset.jsonl --epochs 3
```

Or use the [Colab notebook](helpstral/train_colab.ipynb).

After training, the script appends `HELPSTRAL_MODEL_ID` to `.env`.

### Dataset format (JSONL)

```json
{"messages":[
  {"role":"user","content":[
    {"type":"text","text":"Analyze this image. Respond with DISTRESS or SAFE."},
    {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}
  ]},
  {"role":"assistant","content":"SAFE"}
]}
```

---

## Costs and docs

- **Mistral API:** ~$4 per fine-tuning job + $2/month storage per model. See [Mistral pricing](https://mistral.ai/technology/#pricing).
- **Local LoRA:** Free (Colab T4), ~15 GB VRAM.
- **Docs**: [Fine-tuning guide](https://docs.mistral.ai/guides/finetuning/), [Cookbook](https://docs.mistral.ai/cookbooks/mistral-fine_tune-mistral_finetune_api), [Models](https://docs.mistral.ai/getting-started/models).
