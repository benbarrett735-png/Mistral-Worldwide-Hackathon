# Hackathon submission & how judges assess the fine-tuned models

## What you actually submit

You **do not** upload model weights or a model file. With Mistral API fine-tuning, the model stays on Mistral’s servers; you get a **model ID** (e.g. `ft:pixtral-12b-latest:your-org:helpstral:abc123`).

You submit **the project**, in the way the hackathon specifies (e.g. Devpost, Luma, or a form):

1. **Link to your code** – GitHub (or similar) repo.
2. **Short project description** – what it does, who it’s for, how it uses Mistral.
3. **Video** – usually ≤ 2 minutes: demo + pitch (show the app and the two models in action).

Judges look at the repo, the writeup, and the video. They do **not** get a copy of your model; they assess your **fine-tuning** via your documentation and demo.

---

## How judges assess the fine-tuned models

From the rules and fine-tuning track:

### Shared criteria (all tracks, 25% each)

- **Impact** – Long-term potential, growth, real-world use.
- **Technical implementation** – How well the idea is built.
- **Creativity** – Novelty and originality.
- **Presentation** – How clearly and convincingly you present.

### Extra for the fine-tuning track

Judges also look at:

- **Effort** – Time and thought put into data and training.
- **Technical skillset** – Data prep, training pipeline, evaluation.
- **Amount of data** – Size and relevance of training data.
- **Data cleaning** – How you sourced, labeled, and cleaned data.
- **Task clarity** – What the base model does badly vs what your fine-tuned model does well.
- **Evidence** – Logs, metrics, or before/after examples.
- **Improvement** – Before vs after fine-tuning (accuracy, examples, or qualitative comparison).

So they’re judging: “Did you really fine-tune? On what? How much better is it? Can we see that in the app and in your docs?”

---

## What to put in the repo so judges can assess

Give judges a clear, self-contained story. Suggested places:

### 1. README (or a “Fine-tuning” section)

- State that you used **Mistral’s fine-tuning API** (base: e.g. `pixtral-12b-latest`).
- Name the two models and their roles:
  - **Helpstral** – image → SAFE / DISTRESS.
  - **Flystral** – image → flight command (e.g. `FOLLOW|0.7`).
- One or two sentences each on:
  - Dataset size and source (e.g. “~22 synthetic + N real images”).
  - What you tuned for (e.g. “distress vs safe”, “structured command output”).

### 2. Model IDs (for reproducibility, optional but strong)

In README or a short `FINE_TUNING.md` / `JUDGING.md`:

- The **fine-tuned model IDs** you use in the app (from `.env` after training), e.g.  
  `HELPSTRAL_MODEL_ID=ft:pixtral-12b-latest:...`  
  `FLYSTRAL_MODEL_ID=ft:pixtral-12b-latest:...`
- Note: “These IDs are for our Mistral account; judges can run training themselves with the datasets in the repo.”

So judges see you actually have custom models and can, if they want, rerun `train.py` with your data.

### 3. Before / after (recommended)

A small “Before vs after” subsection or file:

- **Before:** e.g. “Base Pixtral with a prompt often returns long text or wrong labels.”
- **After:** e.g. “Fine-tuned Helpstral returns only SAFE/DISTRESS; Flystral returns only the chosen command format.”
- If you have numbers: e.g. “We evaluated on 20 holdout images: base X% correct, fine-tuned Y%.”
- If you don’t: 2–3 example inputs and outputs (base vs fine-tuned) in a table or screenshot.

### 4. Datasets in the repo

- **helpstral/dataset/helpstral_dataset.jsonl** (and optionally **flystral/dataset/flystral_dataset.jsonl**) – so judges see size, format, and task.
- In README: “Training data: `helpstral/dataset/helpstral_dataset.jsonl` (N examples), `flystral/dataset/flystral_dataset.jsonl` (M examples).”

This supports “amount of data” and “data cleaning” without you uploading weights.

### 5. Optional: Weights & Biases (or similar)

If you use W&B (or any logging) during training, add a link or a screenshot in README: “Training metrics: [W&B board].” Not required, but it’s strong evidence for “technical skillset” and “effort.”

---

## Checklist before you submit

- [ ] Repo is public and linked in the submission form.
- [ ] README explains the app and names **Helpstral** and **Flystral** as fine-tuned Mistral models (and base model).
- [ ] README (or JUDGING.md) describes datasets (size, what they’re for) and, if possible, before/after or metrics.
- [ ] Dataset files are in the repo (or linked) so judges can see data volume and format.
- [ ] Video shows the full flow and both models (e.g. distress detection + flight commands) in action.
- [ ] Optional: model IDs and “how to reproduce training” (e.g. `python helpstral/train.py …`) documented.

You’re not submitting the tuned model as a file; you’re submitting the **project + evidence** so judges can assess how you tuned the models and how much they improve the application.
