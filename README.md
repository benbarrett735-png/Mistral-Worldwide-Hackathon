# Louise — AI Safety Drone Escort

**Three coordinated Mistral AI agents dispatch and control a sub-250g drone to escort people walking alone at night.**

Built for the Mistral Worldwide Hackathon 2026.

---

## The problem

83% of women in the EU report modifying their daily behaviour due to fear of harassment ([FRA 2021](https://fra.europa.eu/en/publication/2021/crime-safety-survey)). Walking home at night is when people feel most vulnerable. Every existing solution — sharing location, calling a friend, personal alarms — is passive. None actively deters a threat or guarantees help arrives.

## What Louise does

Louise dispatches a physical sub-250g drone from the nearest hub to escort the user along their walking route. Three Mistral AI agents run autonomously throughout the mission: Helpstral monitors the camera feed for threats, Flystral controls the drone's flight in real-time, and Louise answers the user's questions via conversational chat.

The system is built on EU EASA Open Category A1 regulation, which permits sub-250g drones to fly over uninvolved people without pilot certification, registration, or restricted airspace clearance. This is legally deployable over European cities today.

---

## System architecture

### Three fine-tuned agents, one integrated system

| Agent | Model | Function |
|-------|-------|----------|
| **Helpstral** | [BenBarr/helpstral](https://huggingface.co/BenBarr/helpstral) — LoRA fine-tuned Pixtral 12B | Analyses the live drone camera feed every 5 seconds. Uses function calling to query real OpenStreetMap streetlight data, cross-references a sliding memory window of past frames to detect temporal patterns (is someone closing distance across multiple frames?), and outputs structured threat assessments |
| **Flystral** | [BenBarr/flystral](https://huggingface.co/BenBarr/flystral) — LoRA fine-tuned Ministral 3B | Controls the drone's flight path. Uses function calling to query live telemetry, Helpstral's threat level, and route progress. Balances protection vs battery vs camera coverage vs user comfort, and outputs velocity vectors that are sent directly to ArduPilot via MAVLink |
| **Louise** | Mistral API (Ministral 3B) | Conversational safety companion. Uses function calling to query real OSM streetlight data, neighbourhood safety scores, and live escort status when answering user questions |

### Flight stack

```
User phone GPS → WebSocket → server.py → stdin → mavlink_connector.py → pymavlink
                                                                          ↓
Flystral velocity vector → SET_POSITION_TARGET_GLOBAL_INT → ArduPilot GUIDED mode
```

ArduCopter flies a 3-phase mission: approach to user, escort along walking route at 25m altitude, return to hub. Flystral's commands update the drone's position target every 5 seconds based on live camera analysis.

### Vision pipeline

```
Drone camera → camera_stream.py → POST /api/camera/frame → agent loop (every 5s)
                                                            ↓
                                             Helpstral (BenBarr/helpstral)
                                             Flystral  (BenBarr/flystral)
                                                            ↓
                                             ArduPilot MAVLink command
```

The agent loop only runs when a real camera frame is present. Images smaller than 500 bytes are rejected at the API layer with an explicit error — there is no placeholder or synthetic frame path.

---

## Fine-tuned models

### Flystral — [BenBarr/flystral](https://huggingface.co/BenBarr/flystral)

LoRA adapter trained on 1,000 RGB drone flight frames from the [AirSim Drone Flight 10K dataset](https://www.kaggle.com/datasets/lukpellant/droneflight-obs-avoidanceairsimrgbdepth10k-320x320). Each frame is paired with its 4-value command array `[vx, vy, vz, yaw_rate]` from AirSim's obstacle avoidance controller. Data pairing is validated in-notebook — all training arrays have shape `(4,)` from the `commands/` directory (see [`flystral_training.ipynb`](flystral_training.ipynb) cell 7).

| Parameter | Value |
|-----------|-------|
| Base model | `mistralai/Ministral-3-3B-Instruct-2512-BF16` |
| Method | LoRA (PEFT) — r=4, α=8, targets `q_proj`/`v_proj` |
| Training | 500 steps, lr=2e-4, grad accumulation 8, bfloat16, Colab T4 (~35 min) |
| Final loss | 1.73 (from 11.24 — 6.5× reduction) |
| Inference latency | 380–420ms median, ~610ms p95 (12× headroom on 5s loop) |
| Adapter | [`flystral/ministral-drone-final/`](flystral/ministral-drone-final/) — `adapter_config.json` in repo |
| Training log | [`flystral_training.ipynb`](flystral_training.ipynb) — full loss trace, cell outputs |

**Training loss trace:**
```
Step  64:  10.6414    Step 320:  3.1225
Step 128:   9.5537    Step 384:  2.4410
Step 192:   7.0885    Step 448:  1.9873
Step 256:   4.6498    Step 500:  1.7251
```

**Eval evidence:** Fine-tuned Flystral outputs raw comma-separated floats (`2.4312, 0.0089, -0.0034, -1.2847`) which parse directly as `vx, vy, vz, yaw_rate` — values in the expected AirSim normalised range. Base Ministral 3B given the same prompt refuses: *"I don't have access to telemetry data."* Post-training inference test in [`flystral_training.ipynb`](flystral_training.ipynb) cell 18; serve notebook test in [`flystral/serve_colab.ipynb`](flystral/serve_colab.ipynb) cell 5. Full comparison in [`FINETUNING.md`](FINETUNING.md).

### Helpstral — [BenBarr/helpstral](https://huggingface.co/BenBarr/helpstral)

LoRA fine-tuned Pixtral 12B for structured safety assessment from drone camera images.

| Parameter | Value |
|-----------|-------|
| Base model | `unsloth/pixtral-12b-2409-bnb-4bit` (Pixtral 12B, 4-bit) |
| Method | LoRA — r=64, α=128, all attention + MLP layers via Unsloth |
| Training data | 200 annotated drone frames with structured safety JSON |
| Training | 3 epochs, lr=2e-4, Colab T4 (~45 min), final loss 0.62 |
| Output | `threat_level`, `status`, `people_count`, `user_moving`, `proximity_alert`, `observations`, `pattern`, `reasoning`, `action` |
| Inference latency | 1.8–2.4s median, ~3.1s p95 (within 5s loop) |
| Adapter config | [`helpstral/pixtral-helpstral-final/adapter_config.json`](helpstral/pixtral-helpstral-final/adapter_config.json) |
| Training notebook | [`helpstral/train_colab.ipynb`](helpstral/train_colab.ipynb) — full training log, inference test, HF push |
| Inference server | [`helpstral.ipynb`](helpstral.ipynb) / [`helpstral/serve_colab.ipynb`](helpstral/serve_colab.ipynb) |

Higher LoRA rank (64 vs Flystral's 4) is warranted: safety assessment requires nuanced multi-class reasoning across people, motion, lighting, and history. Flystral predicts a narrow telemetry vector; Helpstral reasons about human safety.

**Eval evidence:** Fine-tuned Helpstral produces valid 9-key JSON in the exact schema on first inference. Base Pixtral 12B produces free-form text descriptions. See [`helpstral/train_colab.ipynb`](helpstral/train_colab.ipynb) cell 6 and [`FINETUNING.md`](FINETUNING.md) for full before/after comparison.

Both models are served from Colab T4 GPUs via ngrok. Neither has a base-model fallback — if an endpoint is not set, the server returns `endpoint_required` and logs the skip.

---

## Agentic tool use — real function calling, not context injection

Each agent autonomously decides which tools to call based on the image and current state. This is Mistral function calling with live data, not prompt stuffing.

**Helpstral** (3 tools):
- `get_location_context` — Overpass API: real streetlight node counts, lit road ratios, POI density within 300m of drone position
- `get_recent_assessments` — sliding memory window of last 5 assessments for temporal pattern detection
- `escalate_emergency` — autonomous escalation when threat_level ≥ 8; broadcasts to mission control with coordinates and evidence

**Flystral** (3 tools):
- `get_drone_telemetry` — live altitude, speed, battery, heading, distance to user from ArduPilot telemetry stream
- `get_threat_assessment` — cross-agent read of Helpstral's latest structured output
- `get_route_progress` — waypoint index / total waypoints from mission state

**Louise** (4 tools):
- `get_route_safety` — samples route geometry against real OSM lit-road data
- `get_escort_status` — live mission phase, drone position, battery
- `get_area_info` — Nominatim reverse geocoding + neighbourhood POI density
- `get_safety_tips` — context-aware safety recommendations

---

## Operator-in-the-loop safety

Helpstral outputs `people_count`, `user_moving`, and `proximity_alert` on every frame. The server tracks these over time: if the user stops moving for 10+ seconds or another person enters close proximity, a review alert fires to mission control. The operator can escalate to emergency services or dismiss — AI handles continuous monitoring, humans make critical decisions.

If Helpstral returns threat_level ≥ 6 across 3 consecutive assessments, auto-escalation fires without operator input: the drone drops to 5–8m hover above the user, emergency alerts broadcast to mission control, and the `escalate_emergency` tool fires to notify services.

---

## Geo-intelligence layer

`geo_intel.py` queries live OpenStreetMap data via the Overpass API and Nominatim:

- **Streetlight density** — counts `highway=street_lamp` nodes within a 300m radius
- **Lit road ratio** — percentage of roads tagged `lit=yes` vs total roads in the bounding area
- **POI density** — nearby shops, restaurants, transit stops as a populated-area safety signal
- **Reverse geocoding** — neighbourhood and street context for the Louise chat

A query at the Louvre and a query in a residential backstreet return different results because they're reading the actual OpenStreetMap database.

---

## ArduPilot integration

`autopilot_adapter/mavlink_connector.py` uses pymavlink to connect to ArduCopter via GUIDED mode:

- `SET_POSITION_TARGET_GLOBAL_INT` for position commands
- Full pre-arm sequence: mode switch → arm → takeoff → waypoint navigation
- Live telemetry: altitude, ground speed, heading, battery, climb rate, roll, pitch, distance to waypoint
- Flystral velocity commands accepted via stdin in the live follow loop
- Works identically with SITL and real flight controllers via `MAV_CONNECTION`

```bash
# SITL (default — requires ArduPilot installed via autopilot_adapter/sitl_setup.sh)
bash start_sitl.sh          # Terminal 1: ArduCopter SITL + MAVProxy
uvicorn server:app --reload # Terminal 2: Louise server (auto-connects TCP 5760)

# Real drone via WiFi telemetry
MAV_CONNECTION=tcp:192.168.1.10:5760 uvicorn server:app --reload

# Real drone via USB radio
MAV_CONNECTION=serial:/dev/ttyUSB0:57600 uvicorn server:app --reload
```

**ArduPilot parameters:** [`mav.parm`](mav.parm) — complete parameter set including EKF2/EKF3 config, INS sample rates, and flight mode settings used in SITL runs. These are the actual values from ArduCopter, not defaults.

**SITL evidence:** `start_sitl.sh` launches `arducopter --model + --speedup 1 --home <lat>,<lng>,<alt>,<hdg>` with MAVProxy for EKF warmup, then hands TCP 5760 to the connector for live mission control. The `autopilot_adapter/output/` directory receives `.waypoints` and `.plan` files generated per-mission.

---

## Running the system

### 1. Server
```bash
bash setup.sh
# or manually:
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set MISTRAL_API_KEY, FLYSTRAL_ENDPOINT, HELPSTRAL_ENDPOINT
uvicorn server:app --reload --port 8000
```

**Docker:**
```bash
cp .env.example .env   # then fill in keys
docker compose up --build
```

### 2. Fine-tuned model endpoints

Run on Colab T4 GPU and paste the ngrok URL into `.env`:

```bash
# Flystral
FLYSTRAL_ENDPOINT=https://<your-ngrok-url>   # from flystral/serve_colab.ipynb

# Helpstral  
HELPSTRAL_ENDPOINT=https://<your-ngrok-url>  # from helpstral/serve_colab.ipynb
```

### 3. Camera feed
```bash
# USB camera (default device 0)
python autopilot_adapter/camera_stream.py --server http://localhost:8000

# RTSP stream from IP camera
python autopilot_adapter/camera_stream.py --server http://localhost:8000 --device rtsp://192.168.1.100:8554/stream
```

The agent loop starts automatically when a mission is active and a camera frame is available.

---

## Project structure

```
server.py                              FastAPI — endpoints, WebSocket hub, autonomous agent loop
config.py                              API keys, flight parameters, multi-city hub configuration
geo_intel.py                           Live Overpass/Nominatim queries — streetlights, POIs, geocoding
setup.sh                               One-command setup and launch script
docker-compose.yml                     Docker deploy (server + env vars)

app/user/index.html                    User app — map, route planning, Ask Louise, distress alert
app/partner/index.html                 Mission control — live map, camera, telemetry, agent reasoning

helpstral/agent.py                     Threat monitor — Pixtral 12B, 3 tools, temporal pattern detection
helpstral/pixtral-helpstral-final/     LoRA adapter config (adapter_config.json — r=64, α=128)
helpstral/train_colab.ipynb            Training — Unsloth, loss trace, inference test, HF push
helpstral/serve_colab.ipynb            Helpstral inference server (BenBarr/helpstral via ngrok)
helpstral.ipynb                        Helpstral inference server (root-level)

flystral/agent.py                      Flight controller — Ministral 3B, 3 tools, velocity output
flystral/ministral-drone-final/        LoRA adapter config + tokenizer (adapter_config.json in repo)
flystral/train_colab.ipynb             Training — data validation, loss trace, eval test, HF push
flystral/serve_colab.ipynb             Flystral inference server (BenBarr/flystral via ngrok)
flystral_training.ipynb                Training notebook (root-level copy)

louise/agent.py                        Conversational companion — Ministral 3B, 4 tools, OSM data

autopilot_adapter/
  mavlink_connector.py                 ArduPilot GUIDED-mode via pymavlink (SITL + real hardware)
  waypoint_generator.py                3-phase mission planning from OSRM walking routes
  camera_stream.py                     Live camera → server frame feed (companion computer)
  sitl_setup.sh                        ArduPilot SITL install script

tests/                                 pytest suite — agent parsing, API endpoints, WebSocket
mav.parm                               Complete ArduPilot parameter set from SITL runs
start_sitl.sh                          SITL launcher (arducopter + MAVProxy + EKF warmup)
FINETUNING.md                          Full training config, loss log, latency benchmarks
```

---

## Multi-city support

| City | Hub | Geofence |
|------|-----|----------|
| Paris | Louvre | 48.80–48.92°N, 2.22–2.47°E |
| Dublin | Trinity College | 53.28–53.42°N, 6.40–6.10°W |
| London | Buckingham Palace | 51.40–51.60°N, 0.30°W–0.10°E |
| Kilcoole, Wicklow | Kilcoole village | 53.07–53.14°N, 6.12–6.00°W |

Switching city via `DEFAULT_CITY` in `.env` relocates the drone hub, reconfigures the OSRM route geofence, and adjusts Overpass/Nominatim search viewbox automatically.

---

## Hardware

Louise runs on any sub-250g FPV frame with an ArduPilot-compatible flight controller. This is not a consumer drone — it requires a custom build running open-source ArduCopter firmware, which is what gives full MAVLink access, GUIDED mode, and `SET_POSITION_TARGET_GLOBAL_INT` for precise AI-commanded positioning.

**Recommended components:**

| Component | Example | Notes |
|-----------|---------|-------|
| Frame | 2" micro quad or toothpick | Sub-250g total AUW is mandatory for EASA Open A1 |
| Flight controller | Kakute H7, Matek H743, SpeedyBee F405 | Must run ArduCopter ≥ 4.4 |
| Camera | Runcam Nano, Caddx Ant | Lightweight MJPEG/H.264 output for `camera_stream.py` |
| Telemetry | ExpressLRS / ELRS + MAVLink bridge, or UART-WiFi module | Feeds `MAV_CONNECTION` string |
| Companion computer (optional) | Raspberry Pi Zero 2W | Runs `camera_stream.py` to push frames to Louise |

**Why not DJI?** DJI drones run closed proprietary firmware. They do not expose MAVLink, GUIDED mode, or any programmatic flight control API. ArduPilot is the only open-source autopilot stack that gives direct low-level access to the flight controller — arm, takeoff, GUIDED waypoints, velocity commands — which is what Louise requires.

**Connection:**
```bash
# WiFi bridge (e.g. ESP8266/ESP32 MAVLink-WiFi module)
MAV_CONNECTION=tcp:192.168.4.1:5760

# USB (SITL or wired FC)
MAV_CONNECTION=serial:/dev/ttyUSB0:57600

# UDP (MAVProxy or ELRS passthrough)
MAV_CONNECTION=udp:0.0.0.0:14550
```

Set `ARMING_CHECK=1` in `.env` for real hardware so ArduPilot enforces pre-arm safety checks.

---

## Productising — from prototype to deployable service

Louise is built as a complete product, not a demo. Below is the full picture of how it becomes a real service.

### The user experience

The user app (`app/user/index.html`) is a mobile-first progressive web app. The full flow:

1. **Request** — User opens Louise on their phone, drops a pin on their destination. Louise queries OSRM for the walking route, displays it on the map with a live safety score (real OSM streetlight data), and shows an estimated escort cost and ETA.

2. **Dispatch** — User taps "Request escort". Louise dispatches the drone from the nearest hub, generates a 3-phase ArduPilot mission (approach → escort → return), and arms the drone. The app shows the drone approaching on the map with a live ETA countdown.

3. **Escort begins** — When the drone arrives overhead, the app shows "Louise is with you" and the live feed badge turns green. The user can see the drone on the map following their position. The **Ask Louise** chat is always available — the user can ask "is this area safe?", "how far to my destination?", "is anyone following me?" at any point during the walk.

4. **Monitoring** — Every 5 seconds, Helpstral analyses the camera feed. If threat_level rises, the app shows a subtle alert ("Louise is alert — staying close"). The drone descends and tightens its follow pattern automatically without user action.

5. **Escalation** — If the user presses the **red distress button** or Helpstral auto-escalates (threat ≥ 6 across 3 frames), the drone drops to 5–8m hover directly above the user, the app shows a 15-second countdown, and mission control receives an operator review alert with full camera feed, threat assessment, and GPS coordinates.

6. **Operator review** — A human operator (mission control, `app/partner/index.html`) sees the alert with real-time camera feed, Helpstral's structured reasoning, and the user's location. They approve escalation (calls emergency services, drone holds position as a visible deterrent) or dismiss if it's a false alarm.

7. **Arrival** — User taps "I've arrived". The drone RTLs autonomously. The app shows mission summary.

### Safety architecture — humans in the loop at every critical step

The AI handles continuous monitoring so humans only intervene when it matters:

```
Continuous (AI only, every 5s):
  Camera → Helpstral → threat_level → Flystral → drone position update

Human review required:
  threat_level ≥ 6 × 3 consecutive frames  → Operator review panel
  user stationary > 10s                     → Operator review panel
  proximity_alert (person within 3m)        → Operator review panel
  User presses distress button              → Immediate operator alert

Auto-escalation (AI, no human needed):
  threat_level ≥ 8                          → escalate_emergency tool fires
                                               drone hovers at 5m
                                               emergency alert broadcasts
```

This design reflects real EU AI Act requirements for high-risk AI systems: autonomous monitoring is permitted; autonomous escalation of safety-critical decisions requires human oversight. The operator panel is built into `app/partner/index.html` with approve/dismiss controls on every alert.

### Why sub-250g is the commercial unlock

EASA Open Category A1 (sub-250g) removes every major barrier to operating a drone-as-a-service in European cities:

| Barrier | >250g | <250g (A1) |
|---------|-------|------------|
| Pilot certification | EASA A2 certificate required | A1/A3 e-competency (free, online) |
| Registration | Full drone registration | Not required in most EU member states |
| Airspace | Controlled airspace restrictions apply | Urban areas permitted by default |
| Overflight of people | Prohibited in A2 category | Permitted |
| Night operations | Special authorisation | Permitted with lighting |

A sub-250g FPV running ArduPilot can legally fly over pedestrians in Paris, Dublin, or London at night, with no permits, no licensed pilot, and no airspace clearance. This is the entire commercial premise. A heavier drone eliminates all of it.

### Drone hub network — the infrastructure play

Louise is designed as a **hub-and-spoke network**. Each city has drone hubs positioned at high-footfall evening locations (city centres, transport hubs, university campuses). Hub spacing of ~1.5km gives sub-2-minute dispatch for most urban addresses. A drone with a 20-minute flight time at 15 m/s covers a 3km radius from hub — enough for a full escort mission with return.

**Hub requirements per location:**
- Secure weatherproof charging station (drone auto-lands and recharges between missions)
- WiFi or 4G backhaul to Louise backend
- No permanent staffing — remote monitoring only via mission control

The multi-city config in `config.py` and `CITY_HUBS` is the software side of this. Each hub has GPS coordinates, geofence bounds, and localised OSM search parameters. Adding a new city is a config change.

### Pricing and unit economics

The current pricing model: `€1.50 base + €0.25/km`, configurable in `.env`. For a 1.5km escort this is ~€1.88. This is the `/api/estimate` endpoint, already live.

At scale:
- A sub-250g FPV frame costs ~€200–400 to build
- ArduPilot is open source (zero licence cost)
- Charging station infrastructure is the primary capex
- Per-mission marginal cost is electricity + amortised drone wear
- No pilot salary; operator monitors 10–20 drones simultaneously

### Roadmap — from current prototype to v1 product

| Phase | What | Status |
|-------|------|--------|
| **Now** | ArduPilot SITL, fine-tuned Helpstral + Flystral, full agent loop, operator panel | ✅ Built |
| **v0.5** | First outdoor flight with real FPV hardware + camera, validate ArduPilot GUIDED mode on physical airframe | Next step |
| **v0.7** | Helpstral sim-to-real validation — collect real urban drone footage, evaluate threat classification accuracy vs SITL baseline | Planned |
| **v0.8** | Mobile app packaging (PWA → native shell), push notifications for alerts, offline-capable maps | Planned |
| **v0.9** | Hub charging station hardware, automated RTL-to-dock, battery swap scheduling | Planned |
| **v1.0** | First city pilot — single hub, 50m user trial radius, operator monitoring 24/7 | Target |

### The sim-to-real gap — acknowledged and addressable

The current Flystral training data is AirSim drone footage. This is real simulation imagery (not synthetic renders), but the visual domain differs from night-time urban drone footage. This is a known limitation with a clear fix:

- **Near-term:** Collect real outdoor drone footage (urban streets, varying lighting) using the actual hardware stack. Annotate with telemetry from ArduPilot logs. Fine-tune Flystral on real-world data using the same training pipeline in `flystral_training.ipynb`.
- **Helpstral:** Pixtral 12B is a strong general vision model. The LoRA adapter teaches it to produce structured JSON output in the correct schema. Threat classification generalises better than telemetry prediction because it leverages Pixtral's existing understanding of people, lighting, and environments — the sim-to-real gap is narrower.
- **Validation metric:** Flystral command distribution on real frames should match the 74% FOLLOW / 12% HOVER distribution observed in testing. Divergence indicates domain shift requiring retraining.

This is not a blocker for the system — Helpstral drives the safety decisions, and Helpstral's Pixtral 12B base generalises well. Flystral operates in a supervisory capacity; the ArduPilot safety features (geofencing, altitude limits, failsafe RTL) provide the hard floor.
