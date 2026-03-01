# Louise — AI Safety Drone Escort

**A multi-agent system that dispatches a drone to escort people walking alone at night, powered by three coordinated Mistral AI agents.**

Built for the Mistral Worldwide Hackathon 2025.

---

## The problem

In the EU alone, 83% of women report modifying their behaviour due to fear of harassment ([FRA 2021](https://fra.europa.eu/en/publication/2021/crime-safety-survey)). Walking home at night is when people feel most vulnerable — and existing solutions (sharing location with a friend, calling someone) are passive. They don't actively protect you.

## The solution

Louise dispatches a sub-250g drone to physically escort you along your walking route. Three Mistral-powered AI agents run continuously during the mission: one monitors the environment for threats, one controls the drone's flight path in real-time, and one provides a conversational safety companion the user can chat with.

The system is designed around the EU's sub-250g drone category (EASA Open Category A1), which allows flight over people without pilot certification, registration, or restricted airspace authorisation — making this deployable today under existing regulation.

---

## How it works

1. **Request** — User opens the app, sets origin and destination, taps "Request drone escort"
2. **Dispatch** — Louise plans a walking route via OSRM, generates a 3-phase flight plan (approach → escort → return), and launches the drone from the nearest hub via ArduPilot
3. **Escort** — The drone follows the user along their route at 25m altitude. Three AI agents run autonomously every 5 seconds:

| Agent | Model | Role |
|-------|-------|------|
| **Helpstral** | Pixtral 12B | Analyses the drone camera feed for threats. Queries live OpenStreetMap data (streetlight density, lit road ratio, nearby POIs) via function calling, cross-references with a sliding memory window of past assessments to detect temporal patterns (someone following, entering darker areas) |
| **Flystral** | [Fine-tuned Ministral 3B](https://huggingface.co/BenBarr/flystral) | Controls the drone's flight. Queries telemetry, Helpstral's threat assessment, and route progress via function calling. Balances four competing priorities: user protection, battery conservation, camera coverage, and user comfort |
| **Louise** | Ministral 3B | Conversational AI the user can chat with during their walk. Answers questions about route safety using real geo-intelligence data (streetlights, neighbourhood info, POI density from OpenStreetMap) |

4. **Escalation** — If Helpstral detects threat_level >= 6 for 3 consecutive assessments, the system auto-escalates: emergency alerts fire, the drone drops to 5-8m hover directly above the user, and emergency services can be notified
5. **Arrival** — When the user reaches their destination, the drone returns to the hub autonomously

---

## Why sub-250g matters

Under [EASA regulation (EU) 2019/947](https://www.easa.europa.eu/en/domains/civil-drones-rpas), drones under 250g in the Open Category A1 subcategory can:

- Fly over uninvolved people
- Operate without pilot certification (A1/A3 competency is free online)
- Fly without registration in most member states
- Operate in urban areas without restricted airspace authorisation
- Fly at night (with appropriate lighting)

This means Louise doesn't require a licensed pilot, special permits, or restricted airspace clearance. A network of autonomous sub-250g drones can legally operate over European cities today. The DJI Mini 4 Pro (249g) already carries a 4K camera with obstacle avoidance — the hardware exists.

---

## What makes this genuinely agentic

This is not prompt engineering wrapped in an API. Each agent uses Mistral's function calling to autonomously decide what information it needs, fetch it, reason over it, and act.

**Helpstral** calls three tools:
- `get_location_context` — queries the Overpass API for real streetlight counts, lit road ratios, and POI density within 300m of the drone's position
- `get_recent_assessments` — retrieves a sliding window of its own past assessments to reason about temporal patterns (is someone getting closer frame-over-frame?)
- `escalate_emergency` — autonomously triggers emergency protocol when threat_level >= 8

**Flystral** calls three tools:
- `get_drone_telemetry` — live altitude, speed, battery, heading, distance to user
- `get_threat_assessment` — cross-agent query to Helpstral's latest analysis
- `get_route_progress` — percentage complete, remaining distance

**Louise** calls four tools:
- `get_route_safety` — samples 5 points along the route with real OSM streetlight/lighting data
- `get_escort_status` — live mission status, drone position, phase
- `get_area_info` — reverse geocoding + neighbourhood POI density
- `get_safety_tips` — context-aware safety recommendations

The autonomous loop runs every 5 seconds without human triggering. Helpstral analyses the frame, Flystral adapts the flight, and if threats persist across 3+ consecutive assessments, auto-escalation fires independently.

---

## Fine-tuned models

Flystral is LoRA fine-tuned on real drone flight data to predict telemetry vectors from camera images:

| | |
|---|---|
| **HuggingFace** | [BenBarr/flystral](https://huggingface.co/BenBarr/flystral) |
| **Base model** | `mistralai/Ministral-3-3B-Instruct-2512-BF16` |
| **Method** | LoRA (PEFT) — r=4, α=8, targets `q_proj`/`v_proj` |
| **Dataset** | [AirSim Drone Flight 10K](https://www.kaggle.com/datasets/lukpellant/droneflight-obs-avoidanceairsimrgbdepth10k-320x320) — 1,000 RGB frames paired with telemetry vectors |
| **Training** | 500 steps, lr=2e-4, gradient accumulation 8, bfloat16 on Colab T4 |
| **Notebook** | [`flystral/train_colab.ipynb`](flystral/train_colab.ipynb) |
| **Serving** | [`flystral/serve_colab.ipynb`](flystral/serve_colab.ipynb) — loads model on Colab GPU, serves via Flask + ngrok |

The fine-tuned model is served from a Colab GPU via ngrok. When the endpoint is available, Flystral uses the fine-tuned model; otherwise it falls back to agentic mode on the base Ministral 3B via the Mistral API.

See [`FINETUNING.md`](FINETUNING.md) for full training configuration.

---

## Real-world data, not mocks

The geo-intelligence layer (`geo_intel.py`) queries live OpenStreetMap data via the Overpass API and Nominatim:

- **Streetlight density** — counts `highway=street_lamp` nodes within 300m radius
- **Lit road ratio** — percentage of roads tagged `lit=yes` vs total roads in the area
- **POI density** — nearby shops, restaurants, transit stops (populated areas = safer)
- **Reverse geocoding** — neighbourhood names and context for the user chat

Safety scores are computed from real infrastructure data, not hardcoded values. A query at the Louvre returns different streetlight counts than a query in a residential backstreet — because it's reading the actual map.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# Set MISTRAL_API_KEY in .env (get one at console.mistral.ai)
uvicorn server:app --reload --port 8000
```

- **User app:** http://localhost:8000/user
- **Mission control:** http://localhost:8000/partner

To use the fine-tuned Flystral model, run `flystral/serve_colab.ipynb` on a Colab T4 and set `FLYSTRAL_ENDPOINT` in `.env`.

---

## Project structure

```
server.py                         FastAPI backend — endpoints, WebSocket, autonomous agent loop
config.py                         Configuration — API keys, flight params, multi-city hubs
geo_intel.py                      Live OpenStreetMap queries — streetlights, POIs, geocoding

app/user/index.html               User app — map, routing, Ask Louise chat, distress button
app/partner/index.html            Mission control — live map, camera feed, telemetry, agent reasoning

helpstral/agent.py                Safety monitor — 3 tools, multi-frame temporal reasoning
flystral/agent.py                 Flight controller — fine-tuned endpoint + agentic fallback
flystral/train_colab.ipynb        LoRA fine-tuning notebook
flystral/serve_colab.ipynb        Inference server notebook
flystral/ministral-drone-final/   LoRA adapter (weights on HuggingFace)
louise/agent.py                   Conversational AI — 4 tools, real geo-intelligence

autopilot_adapter/
  waypoint_generator.py           3-phase waypoint generation from walking routes
  mavlink_connector.py            ArduPilot GUIDED-mode flight via MAVLink
  mock_simulator.py               Async drone simulator for testing without ArduPilot
```

---

## Multi-city support

Louise supports deployment across European cities. Each city has a configured drone hub, geofence, and localised search:

| City | Hub location | Status |
|------|-------------|--------|
| Paris | Louvre | Active |
| Dublin | Trinity College | Active |
| London | Buckingham Palace | Active |

The system uses real OSRM routing, real OpenStreetMap data, and real ArduPilot SITL simulation per city. Switching cities relocates the SITL instance and reconfigures the geofence automatically.
