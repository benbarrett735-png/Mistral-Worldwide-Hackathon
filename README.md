# Louise — AI Safety Drone Escort

**Multi-agent drone escort system for people walking alone at night.**

Built for the Mistral Worldwide Hackathon 2025.

---

## What it does

1. User opens the app, sets origin and destination
2. Louise plans a real walking route (OSRM / OpenRouteService)
3. User requests a drone escort — a drone dispatches from the hub (Louvre, Paris)
4. The drone flies to the user, then escorts them along their route
5. **Three AI agents** run continuously during the mission:
   - **Helpstral** — safety monitor. Uses Mistral function calling to query real OSM streetlight/POI data, reviews its own assessment history for temporal patterns, and produces structured threat assessments
   - **Flystral** — flight controller. Queries drone telemetry, Helpstral's threat assessment, and route progress via tool calls, then produces adaptive flight commands with trade-off reasoning
   - **Ask Louise** — user-facing conversational AI. Users chat with Louise about route safety, area info, and safety tips. Louise calls tools that query real OpenStreetMap data
6. If threat persists across 3+ frames, auto-escalation triggers emergency alerts
7. After arrival, the drone flies home automatically

---

## Architecture

```
User App (phone)     -->  POST /api/route       --> OSRM / OpenRouteService
                     -->  POST /api/order       --> Waypoint generator + ArduPilot SITL
                     -->  POST /api/louise      --> Ask Louise agent (Mistral function calling)
                     <--> WebSocket /ws         <-- Live telemetry + agent updates

Partner App (laptop) <--> WebSocket /ws         --> Live map, 3D drone, telemetry, agent reasoning
                     -->  POST /api/agent-loop  --> Helpstral → Flystral coordinated cycle

Autonomous Loop      --> Runs every 5s during active missions
                         Helpstral assesses frame (calls tools) → Flystral decides flight (calls tools)
                         Auto-escalation if 3 consecutive threat_level >= 6

Geo Intelligence     --> Overpass API (streetlights, lit roads, POIs)
                     --> Nominatim (reverse geocoding, neighborhood names)
```

---

## Project structure

```
server.py                         FastAPI backend (endpoints, WebSocket, agent loop)
config.py                         Shared config (API keys, hub coords, model IDs)
geo_intel.py                      Real OSM queries (streetlights, POIs, reverse geocoding)
requirements.txt                  Python dependencies

app/
  user/index.html                 User app — map, routing, Ask Louise chat, distress button
  partner/index.html              Mission control — live map, 3D drone, agent reasoning display

helpstral/
  agent.py                        Helpstral agent with Mistral function calling (3 tools)
  infer.py                        Legacy inference (check_distress)

flystral/
  agent.py                        Flystral agent with Mistral function calling (3 tools)
  infer.py                        Legacy inference (get_command)
  command_parser.py               Parse command to waypoint adjustment

louise/
  agent.py                        Ask Louise agent with Mistral function calling (4 tools)

autopilot_adapter/
  waypoint_generator.py           Generate 3-phase waypoints from route
  mavlink_connector.py            ArduPilot GUIDED-mode connector
  mock_simulator.py               Async drone simulator (no ArduPilot needed)

tests/                            55 tests (agents, API, WebSocket)
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env:
#   MISTRAL_API_KEY=your_key_here
#   ORS_API_KEY=your_openrouteservice_key (free at openrouteservice.org)
#
# Optional fine-tuned model IDs (trained externally, e.g. in Google Colab):
#   HELPSTRAL_MODEL_ID=ft:pixtral-12b:xxx
#   FLYSTRAL_MODEL_ID=ft:pixtral-12b:xxx
#
# Without fine-tuned IDs, the system uses pixtral-12b-2409 with advanced prompts.
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
3. Set origin and destination on the map
4. Tap "Request drone escort"
5. Watch the drone animate across both screens
6. See Helpstral assessments and Flystral reasoning appear in mission control
7. Chat with Louise using the "L" button in the user app
8. Tap "I NEED HELP" to test emergency flow

---

## API reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Redirect to user app |
| `/api/route` | POST | `{origin, destination}` → walking route |
| `/api/order` | POST | `{origin, destination, route}` → dispatch drone |
| `/api/estimate` | POST | `{origin, destination}` → distance + price estimate |
| `/api/helpstral` | POST | `{image}` → structured threat assessment (with tool calling) |
| `/api/flystral` | POST | `{image}` → structured flight command (with tool calling) |
| `/api/agent-loop` | POST | `{image}` → full Helpstral → Flystral cycle |
| `/api/louise` | POST | `{message, conversation}` → Ask Louise response |
| `/api/agent-status` | GET | Current agent state and loop status |
| `/api/config` | GET | Public config (hub, bounds, pricing) |
| `/api/test-frame` | GET | Placeholder JPEG for vision APIs |
| `/ws` | WebSocket | Live telemetry, agent updates, emergency |
| `/health` | GET | System status |

---

## Fine-tuning

Models are fine-tuned externally (e.g. Google Colab) on Pixtral 12B using the Mistral fine-tuning API. The training data format includes tool-calling examples so the models learn when to invoke tools, not just how to output JSON.

After fine-tuning, set the model IDs in `.env`:
```
HELPSTRAL_MODEL_ID=ft:pixtral-12b:your_id
FLYSTRAL_MODEL_ID=ft:pixtral-12b:your_id
```

Without fine-tuned IDs, the system defaults to `pixtral-12b-2409` with advanced prompts.

---

## What makes this agentic

**Not just prompt engineering.** Each agent uses Mistral's function calling API — the model decides which tools to call, receives real results, and reasons over them.

**Helpstral tools:** `get_location_context` (real OSM streetlight/POI data), `get_recent_assessments` (sliding memory window), `escalate_emergency`

**Flystral tools:** `get_drone_telemetry`, `get_threat_assessment` (cross-agent query), `get_route_progress`

**Louise tools:** `get_route_safety` (samples 5 points with real OSM data), `get_escort_status`, `get_area_info` (reverse geocoding + POI density), `get_safety_tips`

**Autonomous loop:** Background task runs every 5s during missions — no manual triggering needed.

**Multi-frame reasoning:** Helpstral tracks patterns across assessments (closing distance, lighting changes, persistent individuals).

**Adaptive flight:** Flystral reasons about trade-offs between protection, battery, camera coverage, and user comfort.
