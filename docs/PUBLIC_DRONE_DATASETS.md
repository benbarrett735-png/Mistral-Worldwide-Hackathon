# Public image databases for people in drone footage

These are free, public datasets you can use to train Helpstral (person / distress in view) and Flystral (drone view → commands). Many include **pedestrians** or **people** in aerial/drone imagery.

---

## 1. **VisDrone (VisDrone2019-DET)** – best fit for “people in drone view”

- **What:** ~8.6k drone images, 10 object classes including **pedestrian** and **people**. Urban/suburban, 14 Chinese cities.
- **License:** CC-BY-SA-3.0 (attribution, share-alike; check for non-commercial).
- **Where:**  
  - Hugging Face (FiftyOne): [Voxel51/VisDrone2019-DET](https://huggingface.co/datasets/Voxel51/VisDrone2019-DET)  
  - Official: [VisDrone-Dataset (GitHub)](https://github.com/VisDrone/VisDrone-Dataset) (images via their download links).
- **How to use:**  
  - With FiftyOne: `pip install fiftyone` then `fiftyone.utils.huggingface.load_from_hub("Voxel51/VisDrone2019-DET")`. You get images + bounding-box labels (pedestrian, people, car, etc.). Sample frames and derive labels (e.g. “has pedestrian” → FOLLOW, “crowd” → HOVER).  
  - Or download the official train/val sets and use the annotation `.txt` files to know which images have pedestrians; then build your JSONL from those images.

---

## 2. **Stanford Drone Dataset (SDD)**

- **What:** 60 aerial videos over Stanford campus; 11k+ annotated agents: **pedestrians**, bicyclists, cars, etc. Top-down drone view.
- **License:** CC BY-NC-SA 3.0 (non-commercial).
- **Where:**  
  - [Stanford CVGL – UAV data](https://cvgl.stanford.edu/projects/uav_data/)  
  - [Kaggle – Stanford Drone Dataset](https://www.kaggle.com/datasets/aryashah2k/stanford-drone-dataset)  
  - Annotations: [flclain/StanfordDroneDataset (GitHub)](https://github.com/flclain/StanfordDroneDataset)
- **How to use:** Download videos, extract frames with OpenCV; use annotations to label frames (e.g. “pedestrian present”, “multiple people”). Then build JSONL from sampled frames.

---

## 3. **UAV123**

- **What:** 123 sequences, 113k+ frames; UAV (drone) view; used for tracking (person, car, boat, etc.).
- **Where:** Hugging Face [xche32/UAV123](https://huggingface.co/datasets/xche32/UAV123) (WebDataset-style).
- **How to use:** Load via HF; sample frames and use sequence/category to assign labels (e.g. “person” sequences for Helpstral or Flystral).

---

## 4. **AerialMPT (DLR)**

- **What:** 14 sequences, 307 frames; aerial imagery 600–1400 m altitude; **2,528 annotated pedestrians** (44k+ points). Good for “person in drone view”.
- **Where:** [DLR – AerialMPT](https://www.dlr.de/en/eoc/about-us/remote-sensing-technology-institute/photogrammetry-and-image-analysis/public-datasets/aerialmpt-a-dataset-for-pedestrian-tracking-in-aerial-imagery) (~75 MB).
- **License:** CC BY-NC-ND 3.0 (non-commercial, no derivatives).
- **How to use:** Download, sample frames; use annotations to get “pedestrian present” (and optionally count) for labels.

---

## 5. **UAV-Human**

- **What:** Large UAV benchmark: **human** action recognition, pose, re-ID. People in drone footage.
- **Where:** [UAV-Human (GitHub)](https://github.com/sutdcv/UAV-Human).
- **How to use:** Download and sample frames; use action/scenario labels or “person present” to build SAFE/FLAG or command labels.

---

## 6. **DroneCrowd / crowd in drone view**

- **What:** Drone-based **crowd** detection and counting.
- **Where:** [VisDrone/DroneCrowd (GitHub)](https://github.com/VisDrone/DroneCrowd).
- **How to use:** Good for “multiple people” or “crowd” → e.g. HOVER or REPLAN in Flystral, or “flag for review” in Helpstral.

---

## 7. **P-DESTRE**

- **What:** Pedestrian **detection, tracking, re-ID** from **aerial devices**; fully annotated.
- **Where:** [P-DESTRE](http://p-destre.di.ubi.pt/) (Digital Commons / UBI).
- **How to use:** Download images + annotations; sample frames with “pedestrian” and optionally “multiple” or “alone” for your labels.

---

## Quick comparison

| Dataset        | People/pedestrian | Drone/aerial | Size (approx) | Easiest use                          |
|----------------|-------------------|-------------|---------------|--------------------------------------|
| VisDrone2019   | ✅ pedestrian     | ✅          | ~8.6k images  | HF + FiftyOne or official download   |
| Stanford Drone | ✅ pedestrians    | ✅          | 60 videos     | Extract frames + annotations         |
| UAV123         | ✅ (person etc.)  | ✅          | 113k rows     | Hugging Face load                    |
| AerialMPT      | ✅ 2.5k ped.      | ✅          | 307 frames    | Download + annots                    |
| UAV-Human      | ✅ human          | ✅          | Large         | GitHub download                      |
| P-DESTRE       | ✅ pedestrian     | ✅ aerial   | Annotated     | Website download                     |

---

## Using them for your training

- **Helpstral:** Use images where a **person is in frame** (and optionally “alone” vs “with others” or “moving” vs “stopped”). Label as SAFE / FLAG_FOR_REVIEW or NORMAL / FLAG using your rules (e.g. “person present + walking” = NORMAL, “person on ground” = FLAG).
- **Flystral:** Use the **same drone images**; label by intended command (e.g. clear path with person → FOLLOW, obstacle in frame → AVOID_LEFT/CLIMB, crowd → HOVER). Use annotation “pedestrian” / “people” to know when the escort target is visible; use “car” / “building” etc. for obstacles.

**Script in this repo:** `flystral/dataset/from_public_drone_dataset.py` loads VisDrone2019-DET from Hugging Face (via FiftyOne), derives Flystral command labels from the built-in annotations (pedestrian/people → FOLLOW, cars/obstacles → AVOID/CLIMB, etc.), and writes `flystral_dataset.jsonl`. Run: `pip install fiftyone` then `cd flystral/dataset && python from_public_drone_dataset.py --max-samples 500`.
