# Mistral Fine-Tuning Guide — Louise / Hackathon

Quick reference for **which Mistral models exist**, **which you can fine-tune**, and **how to run fine-tuning** in this project.

**Yes — you can do all of this with just a Mistral API key.**

**If you get 422 "Model not available for this type of fine-tuning":** Your key may not have fine-tuning enabled, or your region/plan may restrict which models can be fine-tuned. Try starting the job from [La Plateforme](https://console.mistral.ai/build/finetuned-models): upload the same JSONL file, pick the base model (e.g. Pixtral 12B or the one shown as available), and create the job. Then add the returned model ID to `.env` as `HELPSTRAL_MODEL_ID`. You don’t run the training on your machine: you upload your dataset and create a job via the API; Mistral runs the training on their servers and returns a fine-tuned model ID. You then use that model ID for inference (same API). No GPU, Colab, or local training required.

---

## Hackathon assessment: which approach to use

**Use the Mistral API (train from Cursor), not Colab + Unsloth.**

| Factor | Mistral API | Colab + Unsloth + Hugging Face |
|--------|-------------|--------------------------------|
| **Time** | 48h hackathon: upload data, start job, done. No GPU/notebook setup. | Extra setup (Colab, Unsloth, HF), then you must change inference to load your own model. |
| **Judges** | They want: task clarity, full application, evidence, before/after. Your app already uses `HELPSTRAL_MODEL_ID` / `FLYSTRAL_MODEL_ID` → same code path. | You’d need to add a separate inference path (load adapters, run locally or deploy). |
| **Vision** | **Vision fine-tuning is supported.** Use `pixtral-12b-latest` or `ministral-3b-latest` / `ministral-8b-latest` for image-in tasks. | You could fine-tune open vision models (e.g. Ministral on HF) but then inference is on you. |
| **Cost** | ~$4/job + $2/month per stored model. Two models = two jobs + storage. | Free GPU on Colab (limits apply); you own deployment. |

**Conclusion:** Run `helpstral/train.py` and `flystral/train.py` from Cursor with vision base **`pixtral-12b-latest`**. Your dataset format (image URL/base64 + text in `messages`) already matches [Text & Vision Fine-tuning](https://docs.mistral.ai/capabilities/finetuning/text_vision_finetuning). No Colab/Unsloth unless you later want full control over weights.

---

## All Mistral models you could use

### Fine-tunable via API (use these)

From [Text & Vision Fine-tuning](https://docs.mistral.ai/capabilities/finetuning/text_vision_finetuning):

| Base model ID | Type | Best for |
|---------------|------|----------|
| **pixtral-12b-latest** | Vision | Image → label or text (Helpstral, Flystral). **Use this for both.** |
| **ministral-3b-latest** | Vision | Smaller/cheaper vision fine-tuning. |
| **ministral-8b-latest** | Vision | Mid-size vision. |
| **open-mistral-7b** | Text only | Text-only SFT, no images. |
| **mistral-small-latest** | Text only | Small text model. |
| **open-mistral-nemo** | Text only | 12B text-only. |
| **codestral-latest** | Text only | Code-focused. |
| **mistral-large-latest** | Text only | Largest text base in the fine-tune list. |

For **Louise**: use **`pixtral-12b-latest`** for Helpstral (image → SAFE/DISTRESS) and Flystral (image → FOLLOW|0.7 etc.). Optionally try **`ministral-3b-latest`** or **`ministral-8b-latest`** if you want a smaller/cheaper vision run.

### Full Mistral lineup (inference / context)

For completeness — not all of these are fine-tunable; many are inference-only or open-weight.

| Category | Model | API / notes |
|----------|--------|-------------|
| **Frontier generalist** | Mistral Large 3 | Open-weight, multimodal. |
| | Mistral Medium 3.1 | Premier, multimodal. |
| | Mistral Small 3.2 | Open, multimodal. |
| **Ministral (vision + text)** | Ministral 3 14B, 8B, 3B | Open; 3B/8B are fine-tunable as `ministral-3b-latest`, `ministral-8b-latest`. |
| **Reasoning** | Magistral Medium 1.2, Small 1.2 | Premier / open, multimodal reasoning. |
| **Vision (legacy)** | Pixtral 12B | Fine-tunable as `pixtral-12b-latest`. |
| | Pixtral Large | Premier, inference. |
| **Code** | Codestral | Premier; fine-tunable as `codestral-latest`. |
| | Devstral 2 | Open, code agents. |
| **Audio** | Voxtral Mini Transcribe (1 & 2, Realtime) | Premier / open, transcription. |
| **Other** | Mistral Nemo 12B | Open; fine-tunable as `open-mistral-nemo` (text only). |
| | Mistral 7B, Mixtral 8x7B / 8x22B | Open-weight; 7B fine-tunable as `open-mistral-7b`. |
| | OCR 2 / 3, Mistral Moderation, etc. | Specialized APIs. |

Summary: for **fine-tuning in this project**, stick to the first table; for **inference-only** or open-weight use, the second table gives the full picture.

---

## Where to start (after choosing Mistral API)

1. **Get an API key**  
   [La Plateforme](https://console.mistral.ai) → API keys. Put it in `.env` as `MISTRAL_API_KEY`.

2. **Pick your task**
   - **Helpstral**: distress detection (SAFE / DISTRESS) from images → use **`pixtral-12b-latest`** (vision).
   - **Flystral**: image → flight commands (FOLLOW, AVOID_LEFT, etc.) → use **`pixtral-12b-latest`** (vision).

3. **Prepare data**  
   JSONL with `messages`: list of `{ "role": "user"|"assistant", "content": ... }`. For vision, user content can be a list of `{"type":"text","text":"..."}` and `{"type":"image_url","image_url":{"url":"data:image/...;base64,..."}}`.

4. **Run training**  
   Use the existing scripts (see below) or the Mistral cookbook.

---

## How to do it

### 1. Install

```bash
pip install mistralai pandas python-dotenv
```

### 2. Dataset format (JSONL)

Each line is one JSON object:

```json
{"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

For **vision**, user content can be:

```json
{"messages":[
  {"role":"user","content":[
    {"type":"text","text":"Analyze this image. Respond with DISTRESS or SAFE."},
    {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}
  ]},
  {"role":"assistant","content":"SAFE"}
]}
```

Validate/reformat with Mistral’s script:

```bash
wget https://raw.githubusercontent.com/mistralai/mistral-finetune/main/utils/reformat_data.py
python reformat_data.py your_file.jsonl
```

### 3. Upload and create job (Python)

```python
from mistralai import Mistral
import os

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# Upload
with open("train.jsonl", "rb") as f:
    file = client.files.upload(file={"file_name": "train.jsonl", "content": f}, purpose="fine-tune")

# Create job
job = client.fine_tuning.jobs.create(
    model="pixtral-12b-latest", # vision; or "ministral-3b-latest" / "open-mistral-nemo" (text)
    training_files=[{"file_id": file.id, "weight": 1}],
    hyperparameters={"training_steps": 150, "learning_rate": 1e-4},
    suffix="helpstral",
)
# Poll job with client.fine_tuning.jobs.get(job_id=job.id)
# Then use job.fine_tuned_model for inference
```

### 4. Use this repo’s scripts

**Helpstral**

```bash
cd helpstral
python dataset/generate_dataset.py --synthetic   # or --download for real images
python train.py --dataset dataset/helpstral_dataset.jsonl --epochs 3
```

**Flystral**

```bash
cd flystral
python dataset/generate_dataset.py --synthetic
python train.py --dataset dataset/flystral_dataset.jsonl --epochs 5
```

After a run, the script appends `HELPSTRAL_MODEL_ID` or `FLYSTRAL_MODEL_ID` to `.env`. Use that ID in `server.py` and inference scripts.

### 5. Console alternative

You can also create and monitor jobs in [La Plateforme](https://console.mistral.ai/build/finetuned-models) (upload file, choose base model, start job).

---

## Costs and docs

- **Pricing**: Minimum **$4 per fine-tuning job** and **$2/month storage** per model. See [Mistral pricing](https://mistral.ai/technology/#pricing).
- **Docs**: [Fine-tuning guide](https://docs.mistral.ai/guides/finetuning/), [Cookbook (API)](https://docs.mistral.ai/cookbooks/mistral-fine_tune-mistral_finetune_api), [Models](https://docs.mistral.ai/getting-started/models).
