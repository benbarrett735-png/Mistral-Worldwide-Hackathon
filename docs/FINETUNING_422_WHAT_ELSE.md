# 422 "Model not available for fine-tuning" – what else could it be?

You have **billing enabled** and your **files are in Mistral Studio**. The API still returns:

```text
422 – Model not available for this type of fine-tuning (completion). Available model(s): 
```

**Most likely cause (after running the check script):** Your account **can** fine-tune via API, but only **text** models. In the model list, every **Pixtral** (vision) model has `fine_tuning=False`, and **pixtral-12b-latest** does not appear at all. So vision fine-tuning is not available for your key; the 422 is because we request a vision base model.

---

## 1. **Create the job in the Studio UI (recommended for vision)**

Fine-tuning may be enabled in the **console** but not yet for the **same account via API**. Your files are already in Studio, so:

1. Open [console.mistral.ai](https://console.mistral.ai) → **Build** (or **Improve**) → **Fine-tuned models** / **Fine-tune**.
2. Look for **“Create”**, **“New job”**, **“Fine-tune a model”**, or a **“+”**.
3. Select your uploaded file (or upload `helpstral/dataset/helpstral_dataset.jsonl` again).
4. Choose base model **Pixtral 12B** (or whatever the dropdown shows for vision).
5. Start the job. When it finishes, copy the **model ID** (e.g. `ft:pixtral-12b-latest:...`) into `.env` as `HELPSTRAL_MODEL_ID`.

The **Studio UI** may offer Pixtral 12B (or another vision model) for fine-tuning even when the API only exposes text models for your account. After the job completes in the UI, set `HELPSTRAL_MODEL_ID` in `.env` to the new model ID.

---

## 2. **Use an API key created in the same place as Studio**

If you use **La Plateforme** (e.g. a different URL than `console.mistral.ai`), your `.env` key might be from a **different product or region** than where you see files and billing.

- In the **same** Mistral product where you see your files and billing, go to **Settings** (or **API keys** / **Organization**).
- **Create a new API key** there.
- Put that key in `.env` as `MISTRAL_API_KEY` and run `python helpstral/train.py` again.

Same account, same product, same key often fixes “available model(s): ” being empty.

---

## 3. **Organization vs project**

If your account has **organizations** or **projects**, fine-tuning might be enabled for one and not the other.

- In the console, check whether you have a **workspace / organization / project** selector.
- Ensure the **API key** is created in the same org/workspace where you see billing and files.
- Create a new key in that org and use it in `.env`.

---

## 4. **Explicit fine-tuning opt-in**

Some accounts need an extra step to enable **fine-tuning** even after billing is on.

- In **Settings**, **Billing**, or **Organization**, look for:
  - “Fine-tuning”, “Model customization”, “Custom models”, or “Training”.
- Enable it if there’s a toggle or approval step.
- If you don’t see it, ask Mistral support: “How do I enable fine-tuning for my account? I have billing enabled but job create returns 422 with empty available models.”

---

## 5. **Check what your key can see**

From the repo root (with `MISTRAL_API_KEY` in `.env`):

```bash
python scripts/check_mistral_finetuning.py
```

This lists **models** (and whether they have `fine_tuning`), **fine-tuning jobs**, and **uploaded fine-tune files**. If no model shows fine-tuning capability, the key/account doesn’t have fine-tuning via API; use the Studio UI (section 1) or fix key/org (sections 2–4).

---

## Summary

| If… | Then… |
|-----|--------|
| You just want to train | Create the **job in the Studio UI** with your existing file (section 1). |
| You want the API to work | Use an **API key from the same console/org** where billing and files live (sections 2–3), and check for a **fine-tuning** opt-in (section 4). |
| You want to confirm | Run `scripts/check_mistral_finetuning.py` (section 5). |

The 422 with **empty “Available model(s)”** means “this API key is not allowed to start completion fine-tuning for any model.” Fixing key/org or using the UI usually resolves it when billing is already enabled.
