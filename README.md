# Helpstroll & Flystroll

**AI-powered safety drone escort system for people walking alone at night.**

Built for the Mistral Worldwide Hackathon 2025.

---

## What it does

1. **User opens the app** on their phone, taps "Walk me home"
2. They set a destination — the app draws a real walking route using OpenRouteService
3. They tap "Order drone" — a drone dispatches from the hub (Gare du Nord, Paris)
4. The drone flies to the user, then escorts them along their route at 25m altitude
5. **Helpstroll** (fine-tuned Pixtral 12B) watches the camera feed and detects distress
6. **Flystroll** (fine-tuned Pixtral 12B) issues flight commands: FOLLOW, AVOID, CLIMB, REPLAN
7. If the user taps distress and doesn't dismiss in 15 seconds → emergency services alerted
8. After arrival, the drone flies home automatically

---

## Architecture

```
User App (phone)     -->  POST /api/route      --> OpenRouteService (walking directions)
                     -->  POST /api/order      --> Waypoint generator + Mock simulator
                     <--> WebSocket /ws        <-- Live drone position + phase events

Partner App (laptop) <--> WebSocket /ws        --> Live map, drone marker, phase badges
                     -->  POST /api/helpstroll --> Fine-tuned Pixtral 12B (SAFE/DISTRESS)
                                                   POST /api/flystroll --> Fine-tuned Pixtral 12B (FOLLOW|0.7 etc.)

Drone Sim            --> autopilot_adapter/mock_simulator.py
                         3 phases: hub_to_user | track | home
                         Emits position + phase events at 1.5s/waypoint
```

---

## Project structure

```
server.py                         FastAPI backend (all endpoints + WebSocket)
config.py                         Shared config (API keys, Paris coords, model IDs)
requirements.txt                  Python dependencies

app/
  user/index.html                 User app — map, routing, distress button
  partner/index.html              Mission control — live map, telemetry, Helpstroll, Flystroll

autopilot_adapter/
  waypoint_generator.py           Generate 3-phase waypoints from ORS route
  mock_simulator.py               Async drone simulator (position + phase events)
  output/mission.json             Last generated mission
  output/mission.plan             QGroundControl-compatible plan

helpstroll/
  dataset/generate_dataset.py     Build distress/safe JSONL (--synthetic or local images)
  dataset/helpstroll_dataset.jsonl  Training data
  train.py                        Fine-tune via Mistral API
  train_colab.ipynb               Colab notebook (no GPU needed)
  infer.py                        Inference: check_distress(image_b64) -> SAFE|DISTRESS

flystroll/
  dataset/generate_dataset.py     Build vision-to-command JSONL
  dataset/flystroll_dataset.jsonl  Training data
  train.py                        Fine-tune via Mistral API
  infer.py                        Inference: get_command(image_b64) -> {command, param}
  command_parser.py               Parse command to waypoint adjustment
```

---

## Quick start

### 1. Install dependencies

```bash
pip install fastapi "uvicorn[standard]" mistralai httpx python-dotenv websockets
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and set:
#   MISTRAL_API_KEY=your_key_here
#   ORS_API_KEY=your_openrouteservice_key  (free at openrouteservice.org)
```

### 3. Start the server

```bash
uvicorn server:app --reload --port 8000
```

### 4. Open the apps

- User app: http://localhost:8000/user
- Mission control: http://localhost:8000/partner

### 5. Demo flow

1. Open mission control on your laptop
2. Open user app on your phone (or second browser tab)
3. Tap "Walk me home" → tap destination on Paris map
4. Tap "Order drone" → watch drone animate across both screens
5. See Flystroll commands appear in mission control (FOLLOW, AVOID, etc.)
6. Tap "I NEED HELP" → watch 15-second countdown in user app + emergency banner in mission control

---

## Training the models

### Generate datasets

```bash
# Helpstroll: distress/safe detection
python helpstroll/dataset/generate_dataset.py --synthetic

# Flystroll: vision-to-command autopilot
python flystroll/dataset/generate_dataset.py --synthetic
```

For real training, add actual images:
```bash
# Helpstroll: add images to helpstroll/dataset/images/distress/ and images/safe/
python helpstroll/dataset/generate_dataset.py --download

# Flystroll: add aerial images to flystroll/dataset/images/<command>/
python flystroll/dataset/generate_dataset.py
```

### Fine-tune

```bash
python helpstroll/train.py --dataset dataset/helpstroll_dataset.jsonl
python flystroll/train.py  --dataset dataset/flystroll_dataset.jsonl
```

Or use the Colab notebook: `helpstroll/train_colab.ipynb`

After training, model IDs are automatically appended to `.env`.

---

## API reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Redirect to user app |
| `/api/route` | POST | `{origin, destination}` → ORS walking route |
| `/api/order` | POST | `{origin, destination, route}` → dispatch drone |
| `/api/helpstroll` | POST | `{image: base64}` → `{status: SAFE|DISTRESS}` |
| `/api/flystroll` | POST | `{image: base64}` → `{command, param}` |
| `/ws` | WebSocket | Live drone position, phase, and Flystroll events |
| `/health` | GET | System status |

---

## Pitch

> *Every year, thousands of people feel unsafe walking home alone at night. Helpstroll changes that — for €3 per use, a drone can escort anyone, anywhere in the city. Two fine-tuned Mistral vision models watch over them: Helpstroll detects distress from the camera feed, Flystroll autonomously pilots the drone. The moment danger is detected, help arrives in seconds.*

**Why this wins:**
- Two fine-tuned Mistral vision models with clear real-world application
- Full software stack: user app, mission control, backend, drone simulation
- Live demo: real walking routes, animated drone, phase-by-phase tracking
- Strong social impact with quantifiable cost (€3/escort)
- Ready to deploy with real drones (DJI Mini 4 Pro / ArduPilot-compatible hardware)
