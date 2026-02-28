# Training a “flag for human review first” system on footage

**Goal:** You have footage of the user. Train a system that **flags when something seems wrong** and **always sends flags to human review first** (no auto-escalation). Prefer over-flagging over missing something.

---

## Core idea

- **Input:** Frames (or short clips) from the escort camera.
- **Output:** Either “NORMAL – don’t bother operator” or “FLAG_FOR_REVIEW – show to human with optional reason.”
- **Rule:** Only “NORMAL” means no alert. Anything else → mission control sees it and a human decides.

---

## Option 1: Binary (simplest) – NORMAL vs FLAG_FOR_REVIEW

**Labels:** Every frame (or clip) is either:
- **NORMAL** – person walking, scene fine, nothing to worry about.
- **FLAG_FOR_REVIEW** – something might be wrong; human should look.

**Training:** You label footage: “this segment is normal” vs “this segment is worth a look.” Sample frames from each segment into your JSONL. Train the vision model (e.g. Pixtral) to output exactly `NORMAL` or `FLAG_FOR_REVIEW`.

**Pros:** Easiest to train and integrate. Clear rule: anything not NORMAL → human review.  
**Cons:** Operator doesn’t get a “why” (e.g. stopped vs person nearby).

**Best for:** Fast hackathon demo; you can add “why” later.

---

## Option 2: Binary + “when in doubt, flag”

Same as Option 1, but you **bias the system to flag**:

- **Labeling:** When you’re unsure, label the frame as **FLAG_FOR_REVIEW**. So the model sees more “flag” examples at the boundary (weird angle, dim light, someone in the distance, etc.).
- **Prompt:** At inference: “If the scene is clearly normal (person walking alone, well-lit, no concern), respond NORMAL. If anything is unclear or could be concerning, respond FLAG_FOR_REVIEW.”
- **Post-processing (optional):** If the model outputs something that isn’t exactly “NORMAL” (e.g. typo, extra words), treat it as FLAG_FOR_REVIEW. So the default is “send to human.”

Result: fewer missed incidents, more “review” alerts – which is what you want when human always decides.

---

## Option 3: Small set of reasons – NORMAL vs STOPPED | PERSON_NEARBY | STRUGGLE | UNKNOWN

**Labels:** One label per frame (or clip):
- **NORMAL** – no review.
- **STOPPED** – user stopped (could be crossing, could be problem).
- **PERSON_NEARBY** – another person in frame / near user.
- **STRUGGLE_OR_FALL** – possible distress (don’t auto-escalate; still “review”).
- **UNKNOWN** – blur, dark, no person, or can’t tell → review to be safe.

Everything except NORMAL goes to mission control **with the reason** so the operator sees “Stopped” or “Person nearby” or “Unclear scene.”

**Training:** Same pipeline (JSONL, one image + one label). You need enough examples per class so the model doesn’t collapse to UNKNOWN. Start with 50–100+ per label if you can.

**Pros:** Operator gets context; you can later add rules like “person nearby for 30 s” on top.  
**Cons:** More labels and more data needed than binary.

**Best for:** When you have (or can stage) footage for each situation and want a slightly smarter demo.

---

## Option 4: Frames vs short clips

- **Frames only:** One image per example. Easiest with current Mistral vision API. You sample frames from your footage and label each frame. Model learns “this single moment looks normal / worth flagging.”
- **Clips (2–5 s):** If the API supports video or multiple images, you can send a short clip and label the whole clip (“normal walk” vs “person stopped for 5 s” vs “someone approaches”). Better for “sustained” behaviour but more complex.

**Recommendation:** Start with **frames**. Sample 1 frame every 1–2 seconds from your footage, label those. You still get temporal coverage by sending a new frame every few seconds at inference; you can then add app logic like “same flag for 3 frames in a row → one alert” so you’re not flooding the operator.

---

## How to use your footage to build the dataset

1. **Slice footage into segments**  
   - Normal: “user walking alone, well-lit, no one else.”  
   - Flag: “user stopped,” “another person in frame,” “struggle,” “dark/unclear,” etc.

2. **Label segments**  
   - Assign one label per segment (NORMAL or FLAG_FOR_REVIEW for binary; or NORMAL / STOPPED / PERSON_NEARBY / etc. for Option 3).  
   - When in doubt, label as flag (or UNKNOWN).

3. **Sample frames**  
   - From each segment, take 1 frame every 1–2 seconds (or every N frames). Each sampled frame gets the segment’s label.

4. **Build JSONL**  
   - Each line: `{"messages": [{"role": "user", "content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]}, {"role": "assistant", "content": "NORMAL"}]}` (or FLAG_FOR_REVIEW / STOPPED / etc.).  
   - Use a small script: input = folder of images + CSV (or folder structure) with labels; output = `helpstral_dataset.jsonl`.

5. **Balance (rough)**  
   - Don’t make it 99% NORMAL or the model will always say NORMAL. Aim for at least 20–30% “flag” examples (or more if you want to bias toward flagging).

---

## Bias toward “flag” so human review is the default

- **Data:** Include borderline cases as FLAG (or UNKNOWN). E.g. “might be someone in the distance,” “a bit dark,” “user paused for a second.”
- **Prompt:** “Respond NORMAL only when the scene is clearly fine. If anything is ambiguous or could need a human look, respond FLAG_FOR_REVIEW.”
- **Logic:** In code, if the model output is not exactly the string `NORMAL`, treat it as “flag for review.” So parsing errors, typos, or “I’m not sure” all go to the operator.

---

## What to implement first (recommended)

1. **Binary labels:** **NORMAL** vs **FLAG_FOR_REVIEW** (Option 1 + 2).  
2. **Training data:** Frames sampled from your footage (and any staged/synthetic “flag” clips), labeled NORMAL or FLAG_FOR_REVIEW; when in doubt, label FLAG.  
3. **Pipeline:** One vision model (e.g. Pixtral), same API; response is NORMAL or FLAG_FOR_REVIEW; anything other than NORMAL → show in mission control for human review.  
4. **Optional:** Later add a small set of reasons (STOPPED, PERSON_NEARBY, UNKNOWN) and show that in the UI so the operator gets a hint why it was flagged.

That gives you a system trained on “footage of them” that flags when something seems wrong and always sends those flags to human review first.
