# How to actually start a fine-tuning job (Helpstral & Flystral)

**Official doc:** [Text & Vision Fine-tuning | Mistral Docs](https://docs.mistral.ai/capabilities/finetuning/text_vision_finetuning) — dataset format, job create/start, model list (`pixtral-12b-latest` for vision), and FAQ.

You’re on **Improve → Fine-tune** and only see dropdowns for “Custom models” and “Jobs” with **“See documentation”**. Here’s how to get to “create a new job” and what to do if you can’t.

**La Plateforme vs console:** If you’re on **La Plateforme** (e.g. lap.mistral.ai or a different URL), the menu might say “Improve” instead of “Build”. The fine-tuning **create** action is often under a section like **Build** or **Fine-tuned models**; the dropdowns you see are for *listing* existing models/jobs. Look for any **“Create”**, **“New”**, **“+”** or **“Fine-tune a model”** on that same page or in the main nav.

---

## 1. Use the right place in the console

- Go to: **https://console.mistral.ai**
- In the left (or top) nav, look for **“Build”** or **“AI Studio”**, then:
  - **Build → Fine-tuned models**  
    or  
  - Direct link: **https://console.mistral.ai/build/finetuned-models**
- That page is the one where you can **create** a new fine-tuning job (not only list existing custom models / jobs).

If you only see **Custom models** and **Jobs** dropdowns and “See documentation”:

- You might be on a **list** view (existing models/jobs). Look for:
  - **“Create”**, **“New job”**, **“Fine-tune a model”**, **“Start fine-tuning”**, or a **“+”** button (top right or next to “Jobs”).
- Or open the **“See documentation”** link: the doc often points to the exact URL above or says “create your job in the console at …”.

---

## 2. If your account only shows “See documentation”

Some accounts don’t get a “Create job” button until:

- **Billing** is set up (e.g. payment method in **Settings / Billing**).
- **Fine-tuning** is enabled for your plan (e.g. Experiment vs paid plan).

In that case:

- Add a payment method and check **Settings** (or **Organization**) for anything like “Fine-tuning” or “Model customization”.
- Or contact Mistral support / check the help center: “How do I enable fine-tuning?”

---

## 3. Create the job from the UI (when the button is there)

When you’re on **Build → Fine-tuned models** (or the equivalent “create” screen):

1. **Upload** your JSONL:
   - Helpstral: `helpstral/dataset/helpstral_dataset.jsonl`
   - Flystral: `flystral/dataset/flystral_dataset.jsonl`
2. Choose the **base model** (e.g. Pixtral 12B for vision, or whatever the dropdown offers).
3. Set **training steps** / **learning rate** if the form asks (e.g. 150 steps, 1e-4).
4. **Create / Start** the job.
5. When it finishes, copy the **model ID** (e.g. `ft:...`) into `.env` as `HELPSTRAL_MODEL_ID` or `FLYSTRAL_MODEL_ID`.

---

## 4. Create the job via API (if the console never shows “Create”)

If the UI never shows a way to create a job, use the API from your machine. Your dataset is already uploaded (file ID from earlier); you only need to **create the job** with that file.

From the repo root (with `MISTRAL_API_KEY` in `.env`):

```bash
cd helpstral
python -c "
from pathlib import Path
import sys
sys.path.insert(0, str(Path('.').resolve().parent))
from config import MISTRAL_API_KEY
from mistralai import Mistral
client = Mistral(api_key=MISTRAL_API_KEY)

# Re-upload file (or use existing file_id if you have it)
with open('dataset/helpstral_dataset.jsonl', 'rb') as f:
    up = client.files.upload(file={'file_name': 'helpstral_dataset.jsonl', 'content': f}, purpose='fine-tune')
file_id = up.id
print('Uploaded file_id:', file_id)

# Create job (may 422 if model not available for your account)
job = client.fine_tuning.jobs.create(
    model='pixtral-12b-latest',  # or try 'open-mistral-nemo' for text-only
    training_files=[{'file_id': file_id, 'weight': 1}],
    hyperparameters={'training_steps': 150, 'learning_rate': 1e-4},
    suffix='helpstral',
)
print('Job created:', job.id)
print('Check status: client.fine_tuning.jobs.get(job_id=', job.id, ')')
"
```

If you get **422** (“Model not available for this type of fine-tuning”), the API key/plan doesn’t allow that model for fine-tuning; then you **must** use the console (after enabling fine-tuning / billing) or another key that has it.

---

## Summary

- **Where to start a job:** **Build → Fine-tuned models** → look for **“Create” / “New job” / “+”** (exact wording can vary).
- **If you only see “See documentation”:** Set up billing and/or enable fine-tuning; use the doc link to find the create page.
- **If the UI never lets you create:** Use the API script above; if you get 422, you still need to fix access (billing / fine-tuning) and use the console or a different key.
