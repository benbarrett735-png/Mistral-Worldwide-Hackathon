# What data you need to train both models (and how to give it)

## The two models in one sentence

| Model | Input | Output | Job |
|-------|--------|--------|-----|
| **Helpstral** | One image (from the user’s camera / “drone view” of the person) | `SAFE` or `DISTRESS` | Detect if the person in the frame is in distress. |
| **Flystral** | One image (from the drone’s camera, “what’s in front of the drone”) | One command, e.g. `FOLLOW|0.7`, `CLIMB|5`, `AVOID_LEFT|2` | Turn what the drone sees into a flight command: go forward, go up, go around, hover, etc. |

So: **Helpstral = “Is the person okay?”**, **Flystral = “What should the drone do next?”**

---

## What data each model needs

### Helpstral (distress detection)

- **One image per example** – a frame that could be from a phone camera or a drone watching the person.
- **One label per image:** either **SAFE** or **DISTRESS**.
- You need **both** classes (mix of SAFE and DISTRESS). Aim for at least ~20–50 examples total to start; more (100–500) is better for robustness.

**What counts as DISTRESS (examples):**  
Person on the ground, struggle, aggressive posture, someone cornered, dark alley confrontation, running in fear, etc.

**What counts as SAFE (examples):**  
Person walking normally, well-lit street, relaxed posture, empty path, no threat visible.

---

### Flystral (drone “see → command”)

- **One image per example** – what the drone’s camera sees (aerial / forward-looking view).
- **One command per image** – the correct action for that view.

**Commands you’re teaching:**

| Command | Meaning | When to use (examples) |
|---------|--------|-------------------------|
| `FOLLOW|<speed>` | Follow the person ahead | Clear path, person visible. e.g. `FOLLOW|0.7` |
| `AVOID_LEFT|<dist>` | Something on the right → move left | Tree/post/vehicle on right of frame |
| `AVOID_RIGHT|<dist>` | Something on the left → move right | Obstacle on left |
| `CLIMB|<meters>` | Obstacle ahead → go up | Wall, bridge, tree canopy in front |
| `HOVER|<seconds>` | Hold position | Person stopped, or scene unclear |
| `REPLAN|0` | Person left the route → replan | Person turned off path |
| `DESCEND|<meters>` | Too high → come down | Need to get back to escort height |

You need **many images with the right command** for each case. At least ~20–50 total to start; more is better. Spread across FOLLOW, AVOID_LEFT/RIGHT, CLIMB, HOVER, REPLAN, DESCEND so the model sees every command type.

---

## How the data has to look (format)

Both models use **the same kind of file**: **JSONL** (one JSON object per line). Each line is **one training example**.

### One example for Helpstral

- **User:** a short instruction + **one image** (in the format the API expects).
- **Assistant:** exactly **`SAFE`** or **`DISTRESS`**.

Conceptually:

```text
User:   [instruction] + [image]
Assistant: SAFE
```

or

```text
User:   [instruction] + [image]
Assistant: DISTRESS
```

### One example for Flystral

- **User:** a short instruction + **one image** (drone view).
- **Assistant:** exactly **one command** (e.g. `FOLLOW|0.7` or `CLIMB|5`).

Conceptually:

```text
User:   [instruction] + [image]
Assistant: FOLLOW|0.7
```

The **exact** format the code and Mistral API use is in the next section (so you can give us data in a simple form and we can turn it into this).

---

## How to give the data (so we can build the datasets)

You don’t have to write JSONL yourself. You can give us the “raw” material; we turn it into the right JSONL.

### Option A – You add images; we use the repo scripts (easiest)

**Helpstral**

1. You provide:
   - **SAFE:** a folder of images where the person is clearly safe (e.g. walking, well-lit, no threat).
   - **DISTRESS:** a folder of images where you’d say the person is in distress (e.g. struggle, on ground, aggression).
2. Put them in the repo like this:
   - `helpstral/dataset/images/safe/`   → all SAFE images
   - `helpstral/dataset/images/distress/` → all DISTRESS images
3. We run:  
   `python helpstral/dataset/generate_dataset.py`  
   That script builds `helpstral_dataset.jsonl` from those folders (with the right prompt and SAFE/DISTRESS labels).

**Flystral**

1. You provide:
   - Images of “drone view” (aerial or forward-looking), and for each image you tell us the **correct command** (e.g. “this one is FOLLOW|0.7”, “this one is CLIMB|5”).
2. Easiest for us: put images in **one folder per command**, e.g.:
   - `flystral/dataset/images/FOLLOW/`
   - `flystral/dataset/images/CLIMB/`
   - `flystral/dataset/images/AVOID_LEFT/`
   - etc.
   (We can also support a single folder + a CSV/list that says “image1.jpg → FOLLOW|0.7”.)
3. We run:  
   `python flystral/dataset/generate_dataset.py`  
   (once we’ve wired it to read from those folders or from your list). That builds `flystral_dataset.jsonl`.

So: **you give images (and labels/folders or a list); we give you the exact commands and, if needed, small script changes so the generator uses your layout.**

---

### Option B – You give a list or table; we build JSONL

If you don’t want to put images in the repo yet, you can give:

**For Helpstral**

- A list (or table) like:  
  `image1.jpg → SAFE`, `image2.jpg → DISTRESS`, …  
  plus the image files (or links). We can write a small script that:
  - takes that list + the images (or URLs),
  - outputs `helpstral_dataset.jsonl` in the right format.

**For Flystral**

- A list (or table) like:  
  `image1.jpg → FOLLOW|0.7`, `image2.jpg → CLIMB|5`, …  
  plus the image files (or links). Same idea: we script list + images → `flystral_dataset.jsonl`.

So: **you give (file names or URLs + label/command per image); we give you a script and the resulting JSONL.**

---

### Option C – Use public drone/pedestrian image databases

There are **public datasets with people in drone footage** (VisDrone, Stanford Drone Dataset, UAV123, AerialMPT, etc.). We documented them in **`docs/PUBLIC_DRONE_DATASETS.md`** with links and licenses.

- **Flystral:** A script **`flystral/dataset/from_public_drone_dataset.py`** loads **VisDrone2019-DET** from Hugging Face (via FiftyOne), derives command labels from detections (pedestrian → FOLLOW, obstacles → AVOID/CLIMB, etc.), and writes `flystral_dataset.jsonl`.  
  Run: `pip install fiftyone` then `python from_public_drone_dataset.py --max-samples 500 --out flystral_dataset.jsonl`
- You can use the same VisDrone images for **Helpstral** (e.g. “pedestrian present” → SAFE, “no person / unclear” → FLAG) by adapting the script or labeling a subset.

---

### Option D – Use the “fetch and label 100” scripts (Pexels)

Scripts in the repo **find and label** ~100 images per category using the **Pexels API** (free key at [pexels.com/api](https://www.pexels.com/api/)):

- **Helpstral:** `helpstral/dataset/fetch_and_label_100.py` — fetches ~100 SAFE and ~100 DISTRESS images, downloads them, builds `helpstral_dataset.jsonl`.
- **Flystral:** `flystral/dataset/fetch_and_label_100.py` — fetches aerial/drone-style images per command (~15–100 per command), builds `flystral_dataset.jsonl`.

**Steps:** Add `PEXELS_API_KEY=your_key` to `.env`, then run:
`cd helpstral/dataset && python fetch_and_label_100.py --target 100`
`cd flystral/dataset && python fetch_and_label_100.py --target 15`
Then train with `train.py` as usual. No hand-labeling: labels come from the search query.

---

### Option E – Use only what’s in the repo (no new data from you)

The repo already has **synthetic** datasets:

- **Helpstral:** `helpstral/dataset/helpstral_dataset.jsonl` – built from URLs (e.g. Unsplash) and labels SAFE/DISTRESS.
- **Flystral:** `flystral/dataset/flystral_dataset.jsonl` – built from URLs and labels like FOLLOW, CLIMB, AVOID_LEFT, etc.

You can train **right now** with these. They’re small (10 and 22 examples) but enough to run the pipeline and demo. For a stronger hackathon demo, we add real or semi-real data (Option A or B).

---

## Exact JSONL format (for reference)

Each line is one JSON object. **Image** can be:

- A **URL** (e.g. `"url": "https://..."`), or  
- **Base64** (e.g. `"url": "data:image/jpeg;base64,..."`).

**Helpstral – one line (one example):**

```json
{"messages":[{"role":"user","content":[{"type":"text","text":"Analyze this image. Is the person in danger or distress? Respond with exactly one word: DISTRESS or SAFE."},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]},{"role":"assistant","content":"SAFE"}]}
```

**Flystral – one line (one example):**

```json
{"messages":[{"role":"user","content":[{"type":"text","text":"You are Flystral, a drone autopilot AI. Analyze this drone camera image and output exactly one command from: FOLLOW|..., AVOID_LEFT|..., ..."},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]},{"role":"assistant","content":"FOLLOW|0.7"}]}
```

You don’t have to write these by hand; the generator scripts (and any script we add for your list/table) will produce them.

---

## Summary

- **Helpstral:** Image of the person (or scene) → **SAFE** or **DISTRESS**.  
  Data: images + SAFE/DISTRESS labels (folders or list).
- **Flystral:** Image of what’s in front of the drone → **one command** (FOLLOW, CLIMB, AVOID_LEFT, etc.).  
  Data: images + one command per image (folders per command or list).

**How to give it:**  
- **Option A:** Put images in `helpstral/dataset/images/safe|distress/` and `flystral/dataset/images/<COMMAND>/`; we use/adapt the existing generators.  
- **Option B:** Give a list/table (filename or URL + label/command); we build a small script and the JSONL.  
- **Option C:** Use the existing synthetic JSONL and train as-is for a quick demo.

For **real people-in-drone-footage** data, use **Option C** (public datasets + `from_public_drone_dataset.py`). For ~100 per label via search, use **Option D** (Pexels fetch scripts). For custom images, use A or B; for a minimal demo with no new data, use **Option E**.
