# Helpstroll & Flystroll — Mistral Hackathon Project Plan

## Overview

**Two fine-tuned models + software stack for a safety drone system.**

**Location: Paris** — Map, demo route, and pitch are all Paris-based (Mistral is French; Paris is one of the 7 hackathon cities).

| Model | Nickname | Role |
|-------|----------|------|
| **Model 1** | **Helpstroll** | Vision → distress detection. Watches user’s camera feed, escalates when distress detected. |
| **Model 2** | **Flystroll** | Pre-flight: 3D map + user route → generates drone flight path. In-flight: cameras + lidar → obstacle avoidance + re-plan if user changes direction. |

---

## Paris Configuration

| Setting | Value |
|--------|-------|
| **Map center** | `[2.3522, 48.8566]` (Paris centre) |
| **Default zoom** | 15 (street level, 3D buildings visible) |
| **Drone station** | e.g. Gare du Nord area `[2.3553, 48.8809]` or custom |
| **Demo route** | User walks e.g. along Rue de Dunkerque → Rue La Fayette |

### Demo Narrative (Paris)
- "Sarah finishes work at Gare du Nord, walks home through the 10th arrondissement"
- Map shows Paris streets, 3D buildings, Seine visible if zoomed out
- Pitch: "Launching first in Paris, then London, NYC…"

### Map Config (for app)
```
PARIS_CENTER = [2.3522, 48.8566]
PARIS_BOUNDS = [[2.22, 48.80], [2.47, 48.92]]  # Approx city limits
DEFAULT_ZOOM = 15
```

---

## Can We Build This in Cursor?

**Yes.** Cursor is just the IDE. The hackathon doesn’t care where you write code.

- **Fine-tuning** runs in Colab (GPU) or locally.
- **Inference** runs wherever you host the app.
- **Cursor** is for: app code, datasets, training scripts, configs.

---

## Scope: 48 Hours

| Component | Feasible in 48h? | Notes |
|-----------|------------------|-------|
| **Helpstroll** | ✅ Yes | Vision model fine-tuned on distress/no-distress images (~100–500 examples). |
| **Flystroll** | ⚠️ Phased | Full vision→autopilot is hard; start with a simpler v1 (see below). |
| **Web interfaces** | ✅ Yes | User app + partner dashboard. |
| **Login** | ❌ Skip for demo | No auth in 48h; demo mode only. |

---

## Helpstroll — Distress Detection

### Idea
- Input: image from user’s phone camera.
- Output: `DISTRESS` or `SAFE`.
- On `DISTRESS`: trigger escalation (countdown, police call).

### Model Choice
- **Ministral 3** (vision) or a smaller vision model fine-tuned for binary classification.
- Or: fine-tune a vision encoder + small classifier (e.g. CLIP-style).

### Dataset
- ~100–500 images labeled `DISTRESS` vs `SAFE`.
- Sources: staged photos, stock, synthetic (blurred faces, dark alley, etc.).

### Training
- Colab + Unsloth or standard HF `transformers` + LoRA.
- 1–3 hours training.

---

## Flystroll — Full Architecture

### Flow

1. **User pre-inputs walking route** on the map (Paris streets).
2. **Flystroll has 3D city maps** (Paris) → generates drone flight path (corridor above the route).
3. **Drone flies** the planned path.
4. **In-flight:** Onboard cameras + lidar → obstacle avoidance + re-plan if user changes direction.

### Pre-flight: Route → Flight Path

| Input | Output |
|-------|--------|
| User route (waypoints on 2D map) | Drone flight path (3D waypoints, clear of buildings) |

**3D map source:** Mapbox / MapLibre vector tiles (building heights from OSM). Paris 3D buildings at zoom 15+.

**Logic:** Offset user route vertically (30–50m altitude), pathfind to avoid building volumes. Output: MAVLink waypoints.

### In-flight: Cameras + Lidar

| Sensor | Role |
|--------|------|
| **Cameras** (multi-direction) | Detect obstacles, user position, direction change |
| **Lidar** | Obstacle depth, low-light backup |

**Model:** Vision sees camera feed → outputs `AVOID_LEFT`, `FOLLOW`, `REPLAN` → parsed to autopilot commands.

### 48h Scope

| Component | Demo? | Notes |
|-----------|-------|-------|
| 3D map + user route input | ✅ | Paris, user draws route on map |
| Flight path generation | ✅ | Offset route + basic building avoidance |
| Camera → commands | ⚠️ | Flystroll v1: semantic labels, smaller dataset |
| Lidar | 🔲 | Simulated / post-hackathon |
| Re-plan on route change | ⚠️ | "User deviated → recalc path" |

---

## Flystroll — Vision → Autopilot (Implementation Detail)

### What “talk to autopilot” means
- Autopilot expects low-level commands: throttle, yaw, pitch, roll, or waypoints.
- We need: **camera image(s) → high-level decision → autopilot commands**.

### Options (easiest to hardest)

| Approach | Description | Feasibility in 48h |
|----------|-------------|--------------------|
| **A. Semantic + rules** | Model outputs labels (e.g. `PERSON_DETECTED`, `OBSTACLE_LEFT`). You hardcode: if person → follow; if obstacle → avoid. | ✅ Easiest |
| **B. VLM → structured text** | **Ministral 3 (vision)** fine-tuned to output structured text like `FOLLOW|SPEED_0.5`. You parse that and map to autopilot commands. | ✅ Feasible |
| **C. End-to-end control** | Image → [throttle, yaw, pitch] directly. Needs lots of flight data + imitation learning. | ❌ Too heavy for 48h |

**Recommended for hackathon: B (or A as fallback).**

### Flystroll v1 (48h)

1. **Model:** Ministral 3B (vision) or similar vision-language model.
2. **Input:** Single front camera image (or stitched 360 view later).
3. **Output:** Structured string, e.g. `FOLLOW|0.5` or `HOVER|2.0` or `AVOID_LEFT|0.3`.
4. **Mapping layer:** Your code parses that string and sends MAVLink / autopilot commands.

### Flystroll v2 (post-hackathon)

- Multi-camera (360) input.
- Lidar integration.
- Full re-planning on route change.

---

## How Judges Evaluate Fine-Tuned Models

From Jof and the rules:

1. **Task clarity** — What the model struggles with out-of-the-box vs after fine-tuning.
2. **Application** — The full product, not just the model.
3. **Evidence** — W&B boards, logs, metrics, documentation.
4. **Improvement** — Before/after comparisons (e.g. accuracy, qualitative examples).

Best practice: log metrics, show base vs fine-tuned behavior, and demo the full system.

---

## Login — Do We Need It?

**For the hackathon demo: no.**

- Single “Demo” user or hardcoded session.
- Focus on flows: summon, distress, partner view.

Add proper auth only if you continue the project after the hackathon.

---

## Project Structure

```
Mistral Hackathon/
├── PROJECT_PLAN.md           # This file
├── FINAL_FLOW.md             # Full flow spec (user + partner + drone)
├── mistral_drone_hackathon_guide.txt
├── paris-config.ts           # Paris map/drone hub config
│
├── app/
│   ├── user/                 # User app (phone) — login, Walk me home, route, Order drone
│   ├── partner/              # Mission control (laptop) — waypoints, camera, Helpstroll
│   └── shared/               # API, routing, waypoint generation
│
├── helpstroll/               # Distress detection model
│   ├── data/                 # Images: distress/ vs safe/
│   ├── train_colab.ipynb     # Fine-tuning notebook
│   └── infer.py              # Load model, run inference
│
├── flystroll/                # Vision → autopilot model
│   ├── data/                 # (image, command) pairs
│   ├── train_colab.ipynb     # Fine-tuning notebook
│   └── command_parser.py     # Text → autopilot commands
│
└── autopilot_adapter/        # Waypoint generation, MAVLink
    └── waypoint_generator.py # Hub→user, track, home
```

---

## Execution Order (48h)

### Phase 1: Foundation (Sat AM)
1. Set up repo and folder structure.
2. Create Helpstroll dataset (scrape/source 100+ distress/safe images).
3. Start Helpstroll fine-tuning in Colab.

### Phase 2: Helpstroll + App Core (Sat PM)
4. Finish Helpstroll training; export model.
5. Build user app skeleton: Summon, Distress, map (simulated).
6. Integrate Helpstroll for image-based distress check.

### Phase 3: Flystroll v1 (Sun AM)
7. User route input UI (draw path on Paris map).
8. Flight path generation: offset route, output waypoints.
9. Create Flystroll dataset: (image, command) pairs (e.g. 50–100).
10. Fine-tune Ministral 3 vision → obstacle/command output.
11. Command parser → autopilot (or mock for demo).

### Phase 4: Integration + Demo (Sun PM)
12. Partner dashboard (basic).
13. Wire everything together.
14. Demo: video + sync; practice pitch.

---

## Map & Routing Stack (Open Source)

| Component | Choice |
|-----------|--------|
| **Map** | Leaflet + OSM, or MapLibre (3D Paris) |
| **Routing** | OpenRouteService or OSRM (walking) |
| **Geocoding** | Nominatim or OpenRouteService |

## Open Decisions

- [ ] ArduPilot SITL for demo (Docker) or mocked?
- [ ] Login: full auth or demo user for 48h?

---

## Next Steps

1. Confirm autopilot stack (RGPilot / ArduPilot / other).
2. Start collecting/generating Helpstroll images.
3. Create Colab notebook for Helpstroll fine-tuning.
4. Set up app skeleton (Next.js or similar).
