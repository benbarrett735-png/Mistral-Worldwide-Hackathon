# Helpstral & Flystral

**AI-powered safety drone escort system for people walking alone at night.**

Built for the Mistral Worldwide Hackathon 2025.

---

## What it does

1. **User opens the app** on their phone, taps "Walk me home"
2. They set a destination — the app draws a real walking route using OpenRouteService
3. They tap "Order drone" — a drone dispatches from the hub (Gare du Nord, Paris)
4. The drone flies to the user, then escorts them along their route at 25m altitude
5. **Helpstral** (fine-tuned Pixtral 12B) watches the camera feed and detects distress
6. **Flystral** (fine-tuned Pixtral 12B) issues flight commands: FOLLOW, AVOID, CLIMB, REPLAN
7. If the user taps distress and doesn't dismiss in 15 seconds → emergency services alerted
8. After arrival, the drone flies home automatically

---

## Architecture

```
User App (phone)     -->  POST /api/route      --> OpenRouteService (walking directions)
                     -->  POST /api/order      --> Waypoint generator + Mock simulator
                     <--> WebSocket /ws        <-- Live drone position + phase events

Partner App (laptop) <--> WebSocket /ws        --> Live map, drone marker, phase badges
                     -->  POST /api/helpstral --> Fine-tuned Pixtral 12B (SAFE/DISTRESS)
                                                   POST /api/flystral --> Fine-tuned Pixtral 12B (FOLLOW|0.7 etc.)

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
  partner/index.html              Mission control — live map, telemetry, Helpstral, Flystral

autopilot_adapter/
  waypoint_generator.py           Generate 3-phase waypoints from ORS route
  mock_simulator.py               Async drone simulator (position + phase events)
  output/mission.json             Last generated mission
  output/mission.plan             QGroundControl-compatible plan

helpstral/
  dataset/generate_dataset.py     Build distress/safe JSONL (--synthetic or local images)
  dataset/helpstral_dataset.jsonl  Training data
  train.py                        Fine-tune via Mistral API
  train_colab.ipynb               Colab notebook (no GPU needed)
  infer.py                        Inference: check_distress(image_b64) -> SAFE|DISTRESS

flystral/
  dataset/generate_dataset.py     Build vision-to-command JSONL
  dataset/flystral_dataset.jsonl  Training data
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

### 2. Configure API keys and optional real drone

```bash
cp .env.example .env
# Edit .env and set:
#   MISTRAL_API_KEY=your_key_here
#   ORS_API_KEY=your_openrouteservice_key  (free at openrouteservice.org)
# Optional: MAV_CONNECTION=tcp:IP:5760 or serial:/dev/ttyUSB0:57600 for real drone (server then skips SITL).
```

**Map and hub:** The single source of truth for hub and map centre is `config.py` (`DRONE_HUB`, `PARIS_CENTER`). The server and user/partner apps use these via the API. The file `paris-config.ts` is an optional demo reference (e.g. for other frontends) and is not used by the main stack.

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
5. See Flystral commands appear in mission control (FOLLOW, AVOID, etc.)
6. Tap "I NEED HELP" → watch 15-second countdown in user app + emergency banner in mission control

**Video feed (Mission Control):** When no real drone camera stream is available, the partner app uses the placeholder image from `GET /api/test-frame` for Helpstral and Flystral so the vision APIs still run every 5s. To use a real feed, point the "Drone camera" video element at your stream URL or add an endpoint that pushes frames to the server.

---


## Deployment

### Docker

Build the image:

```bash
docker build -t louise .
```

Run the container (pass env from `.env`):

```bash
docker run -p 8000:8000 --env-file .env louise
```

**SITL (ArduPilot simulation):** The container does not start SITL. For full drone simulation, run SITL on the host (e.g. `./start_sitl.sh`) or in a separate container, and set `MAV_CONNECTION` (e.g. `tcp:host.docker.internal:5760`) so the server can connect to it.

## Training the models

### Generate datasets

```bash
# Helpstral: distress/safe detection
python helpstral/dataset/generate_dataset.py --synthetic

# Flystral: vision-to-command autopilot
python flystral/dataset/generate_dataset.py --synthetic
```

For real training, add actual images:
```bash
# Helpstral: add images to helpstral/dataset/images/distress/ and images/safe/
python helpstral/dataset/generate_dataset.py --download

# Flystral: add aerial images to flystral/dataset/images/<command>/
python flystral/dataset/generate_dataset.py
```

### Fine-tune

```bash
python helpstral/train.py --dataset dataset/helpstral_dataset.jsonl
python flystral/train.py  --dataset dataset/flystral_dataset.jsonl
```

Or use the Colab notebook: `helpstral/train_colab.ipynb`

After training, model IDs are automatically appended to `.env`.

---

## API reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Redirect to user app |
| `/api/route` | POST | `{origin, destination}` → ORS walking route |
| `/api/order` | POST | `{origin, destination, route}` → dispatch drone |
| `/api/helpstral` | POST | `{image: base64}` → `{status: SAFE|DISTRESS}` |
| `/api/flystral` | POST | `{image: base64}` → `{command, param}`; broadcasts to WS and sends offset to connector |
| `/api/test-frame` | GET | Placeholder JPEG when no real camera feed; partner uses it for Helpstral/Flystral |
| `/ws` | WebSocket | Live drone position, phase, Flystral, emergency |
| `/health` | GET | System status |

---

## Pitch

> *Every year, thousands of people feel unsafe walking home alone at night. Helpstral changes that — for €3 per use, a drone can escort anyone, anywhere in the city. Two fine-tuned Mistral vision models watch over them: Helpstral detects distress from the camera feed, Flystral autonomously pilots the drone. The moment danger is detected, help arrives in seconds.*

**Why this wins:**
- Two fine-tuned Mistral vision models with clear real-world application
- Full software stack: user app, mission control, backend, drone simulation
- Live demo: real walking routes, animated drone, phase-by-phase tracking
- Strong social impact with quantifiable cost (€3/escort)
- Ready to deploy with real drones (DJI Mini 4 Pro / ArduPilot-compatible hardware)
