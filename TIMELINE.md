# Louise — Project Timeline

## Mistral Worldwide Hackathon 2025 (Online Edition)

**Team:** Ben Barrett
**Track:** Track 2 (Anything Goes) + Fine-tuning
**Submission:** Hack Iterate

---

## Phase 1: Idea & Research (Feb 27, pre-hackathon)

### Concept
"Louise" — an AI-powered safety drone escort system for people walking alone at night. A user requests a drone via their phone; the drone flies out from a hub, escorts them home, and returns. Two fine-tuned Mistral vision models power the system:

1. **Helpstroll** (Louise Vision) — distress detection from the drone camera feed. Fine-tuned Pixtral 12B to classify images as SAFE or DISTRESS.
2. **Flystroll** (Louise Pilot) — autonomous flight commands from drone camera imagery. Fine-tuned Pixtral 12B to output structured commands (FOLLOW, AVOID_LEFT, CLIMB, HOVER, REPLAN, etc.).

### Why this idea
- Strong social impact: thousands of people feel unsafe walking home alone at night
- Clear, quantifiable value proposition: ~€3 per drone escort
- Two distinct fine-tuned models with measurable before/after improvement
- Full-stack demo: user app (phone), mission control (laptop), backend, drone simulation
- Paris-specific: hub at Gare du Nord, real walking routes on Paris streets

### Research completed
- DJI Mini 3 Pro drone limitations (no direct SDK control, waypoint support limited)
- ArduPilot SITL for drone simulation (decided on mock simulator for hackathon speed)
- OpenRouteService for walking directions (free API, 7k req/day)
- Mistral Fine-tuning API for training both models
- CARTO Voyager tiles for Google Maps-style clean map rendering
- Leaflet.js for map UI (no build step, fast iteration)

---

## Phase 2: Architecture & Planning (Feb 27)

### Key decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend | Plain HTML/JS/CSS | No build step, fastest iteration, serves from FastAPI |
| Backend | Python FastAPI | Matches model training scripts, WebSocket built-in |
| Map tiles | CARTO Voyager | Clean Google Maps aesthetic, free |
| Routing | OpenRouteService | Free walking directions, returns polyline |
| Vision model | Pixtral 12B | Mistral's vision model, supports fine-tuning |
| Drone sim | Mock Python simulator | Saves ArduPilot setup time, same demo effect |
| Live sync | WebSocket | Real-time drone position + phase + AI events |

### Architecture
```
User App (phone)     POST /api/route      OpenRouteService
                     POST /api/order      Waypoint generator + Simulator
                     WebSocket /ws        Live drone position

Mission Control      WebSocket /ws        Map + telemetry + phases
                     POST /api/helpstroll Fine-tuned Pixtral 12B
                     POST /api/flystroll  Fine-tuned Pixtral 12B
```

### Files planned
- `server.py` — FastAPI backend (all endpoints + WebSocket)
- `config.py` — shared config (API keys, Paris coords, model IDs)
- `autopilot_adapter/waypoint_generator.py` — 3-phase waypoint generation
- `autopilot_adapter/mock_simulator.py` — async drone position emitter
- `app/user/index.html` — user app
- `app/partner/index.html` — mission control
- `helpstroll/` — distress detection model (dataset, train, infer)
- `flystroll/` — autopilot model (dataset, train, infer, command parser)

---

## Phase 3: First Code (Feb 27–28)

### Backend (server.py)
- FastAPI with 6 endpoints: `/`, `/api/route`, `/api/order`, `/api/helpstroll`, `/api/flystroll`, `/ws`
- WebSocket connection manager broadcasting drone position to all clients
- OpenRouteService integration with straight-line fallback
- Waypoint generation triggered by `/api/order`, saves mission.json + mission.plan
- Mock simulator runs as async background task

### Waypoint generator
- Generates 3 flight phases: hub→user (11 waypoints, descending altitude), track (follows walking route at 25m), home (11 waypoints, ascending)
- `generate_from_ors_route()` accepts ORS polyline coordinates directly
- Outputs QGroundControl-compatible .plan file for ArduPilot integration

### Mock simulator
- `simulate_async()` with callback for WebSocket integration
- Emits position events with lat/lng/alt/phase/waypoint_index
- Phase-change events when flight transitions between approach/escort/return
- 1.5s per waypoint, total ~39s for demo mission

### User app (Louise — Walk Me Home)
- White/light theme, Inter font, modern mobile-first design
- CARTO Voyager map tiles (Google Maps aesthetic)
- GPS geolocation + map tap for origin
- Address search via Nominatim geocoder
- Real walking route from ORS drawn on map
- "Request drone escort" → triggers waypoint generation + simulation
- Live drone marker animating on map via WebSocket
- Distress flow: "I need help" → 15-second countdown → emergency escalation

### Mission control (Louise — Mission Control)
- White sidebar with real-time data, purple/blue Louise branding
- Phase badges (Approach → Escort → Return) updating live from WebSocket
- Telemetry grid: altitude, progress %, phase, waypoint index
- Generated waypoint files display (mission.json, mission.plan, per-phase counts)
- Drone camera panel with live badge
- Louise Vision AI: safety monitor (SAFE/DISTRESS) + autopilot commands
- Event log in monospace font
- Hub shown on map with branded marker + 3km range circle
- Flystroll commands displayed during escort phase (FOLLOW, AVOID, HOVER, etc.)

### Helpstroll model
- Dataset generator: synthetic URL-based (10 records) + local image mode
- JSONL format for Mistral vision fine-tuning
- Training script: uploads to Mistral API, creates fine-tuning job, polls completion
- Inference function: `check_distress(image_b64) -> {status, raw}`
- Colab notebook alternative for free GPU training via Unsloth

### Flystroll model
- Dataset generator: 22 synthetic aerial image + command pairs across 7 command types
- Command distribution: FOLLOW (8), CLIMB (3), HOVER (3), AVOID_LEFT (2), AVOID_RIGHT (2), REPLAN (2), DESCEND (2)
- Training script: same pattern as Helpstroll
- Inference function: `get_command(image_b64) -> {command, param}`
- Command parser: converts model output to waypoint adjustments (lat/lng/alt shifts)

### Integration
- Server broadcasts mock Flystroll commands every 5 position events during track phase
- Partner app displays Flystroll commands in AI panel + event log
- Emergency signal from user app → broadcast to all connected clients
- Mission files served as static files for partner app to display

---

## What's next

- [ ] Get ORS API key for real Paris walking routes
- [ ] Add real drone footage video to camera panel
- [ ] Run actual fine-tuning jobs with larger datasets
- [ ] Test with Mistral API key for live inference
- [ ] Record demo video
- [ ] Write pitch script
- [ ] Submit on Hack Iterate
