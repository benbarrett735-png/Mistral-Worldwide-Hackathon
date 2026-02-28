# Helpstral v2: Person awareness + operator review (not just distress)

## What you want

Helpstral shouldn’t only say “SAFE” or “DISTRESS.” It should:

1. **Understand that there’s a person there** – detect the user (and ideally others).
2. **Track over time** – same person across frames (our user) and notice if **another person** is in frame, and especially if **someone is beside the user for too long** (e.g. tailing).
3. **Interpret behavior** – is the user still walking and fine? Stopped? With someone else?
4. **Flag for human review** – don’t auto-escalate to “distress” or emergency. Instead: **raise the question** and **bring it to the control center** so the operator (you) decides: “Do they need help or not?”

So the flow is: **camera → model understands “person, walking/stopped, alone/near someone” → “worth a look?” → mission control sees it → operator decides.**

---

## Reframed output: states + flag for operator

Instead of only **SAFE** / **DISTRESS**, the model can output something like:

| Concept | Possible values | Meaning |
|--------|------------------|--------|
| **User state** | `WALKING` \| `STOPPED` \| `UNKNOWN` | Is the person we’re escorting moving and okay? |
| **Context** | `ALONE` \| `PERSON_NEARBY` \| `MULTIPLE_PEOPLE` | Is someone else in frame / beside them? |
| **Flag for operator** | `OK` \| `REVIEW` | Should this show up in mission control for a human to decide? |

Examples:

- User walking, no one else → `WALKING` + `ALONE` → `OK` (no need to bother operator).
- User stopped (e.g. at a crossing) → `STOPPED` + `ALONE` → `REVIEW` (“why did they stop?”).
- User walking, someone close behind for a while → `WALKING` + `PERSON_NEARBY` → after N seconds → `REVIEW` (“someone’s been near them – check?”).
- User on ground or struggle → could map to `STOPPED` + `REVIEW` or we keep a `DISTRESS`-like state that always triggers `REVIEW` and maybe a stronger alert.

So the model’s job is: **describe the scene (user state + context)** and optionally **suggest REVIEW**. The app then:

- Shows this in mission control (e.g. “Walking, alone” vs “Stopped – review” vs “Person nearby – review”).
- Optionally tracks “person nearby” over time (e.g. same state for 5–10 frames) and then raises “Someone has been near the user for X s – review?”
- Lets **you** in the control center decide: ignore, watch, or escalate to help.

---

## Training the model for this (same pipeline, new labels)

We keep **one vision model** (e.g. Pixtral), same API and JSONL format, but change **what we train it to output**:

**Option A – Single combined label (simplest)**  
Each image → one of a small set of labels, e.g.:

- `WALKING_ALONE` – user walking, no one else (OK).
- `WALKING_PERSON_NEARBY` – user walking, someone else in frame (could be REVIEW after a few seconds).
- `STOPPED_ALONE` – user stopped (REVIEW).
- `STOPPED_PERSON_NEARBY` – user stopped with someone else (REVIEW).
- `MULTIPLE_PEOPLE` – several people (REVIEW).
- `UNCLEAR` – can’t tell (REVIEW to be safe).

Then in the app we map: anything that’s not `WALKING_ALONE` → show in control center and set “needs review” (and optionally run the “person nearby for too long” logic on consecutive frames).

**Option B – Structured text (more flexible)**  
Model outputs a short line, e.g.  
`USER:WALKING CONTEXT:ALONE FLAG:OK`  
or  
`USER:STOPPED CONTEXT:PERSON_NEARBY FLAG:REVIEW`  
We parse that and drive the same UI and “review” logic.

For a hackathon, **Option A** is usually enough: 5–6 labels, train on a few hundred examples (real or synthetic), and the app + mission control UI use that to “bring it to your attention” instead of auto distress.

---

## “Person beside them for too long” (tracking in time)

The **model** can only look at one frame (or a short clip). “Same person beside them for too long” is **temporal** – we need to track over time.

**Lightweight approach (no heavy tracking):**

- Every few seconds we send a frame to the model and get e.g. `WALKING_PERSON_NEARBY`.
- In the backend or frontend we keep a small state: “last N results” or “how many of the last 10 frames said PERSON_NEARBY?”
- If we see `PERSON_NEARBY` (or similar) for e.g. 5–10 frames in a row (or 15–30 seconds), we **raise a dedicated alert** in mission control: “Someone has been near the user for 30 s – review?”
- Operator then decides.

So: **model = per-frame understanding (user state + alone vs person nearby)**; **app = simple “count consecutive PERSON_NEARBY” and then flag for operator.**

**Later (post–hackathon):** Add real multi-person tracking (e.g. BYTE track / BoT-SORT) so we know “person A = user, person B = other” and can measure “B has been within X m of A for Y seconds.” For the hackathon, the “PERSON_NEARBY for N frames in a row” heuristic is enough to demo the idea.

---

## What we’d change in the repo

1. **Labels and dataset**  
   - New label set (e.g. `WALKING_ALONE`, `WALKING_PERSON_NEARBY`, `STOPPED_ALONE`, …) and update `helpstral/dataset/generate_dataset.py` (and any data you add) to produce JSONL with these labels.

2. **Model output and API**  
   - Helpstral returns one of these states (instead of only SAFE/DISTRESS).  
   - Server and mission control treat anything that’s not “OK” (e.g. not `WALKING_ALONE`) as “show in control center + flag for review.”

3. **Mission control UI**  
   - Show: “User: walking | Context: alone” or “User: stopped | Review” or “Person nearby for 30 s – review.”  
   - Operator actions: “Ignore”, “Watch”, “Send help” (or similar).

4. **Optional: “person nearby for too long”**  
   - Backend or frontend keeps a short history of the last K results; if most are “person nearby”, send a dedicated event to mission control so you can decide.

5. **Distress / emergency**  
   - Either: (a) keep a separate “DISTRESS” state that still triggers a stronger alert (and maybe countdown), or (b) let the operator be the only one who can trigger “send help” after reviewing.

---

## Summary

- **Helpstral v2** = “Is there a person? Are they walking? Alone or with someone? Should this go to the control center?”
- **Tracking** = model sees “person nearby” in many frames → we count that over time and flag “someone beside them for too long” for you to review.
- **Operator in the loop** = model and app **don’t** decide “distress”; they **surface** “worth a look” and **you** in the control center decide if they need help.

If you want to go this direction, next step is: lock the exact label set (Option A above or a variant), then we adapt the dataset generator, training, and API/UI to that.
