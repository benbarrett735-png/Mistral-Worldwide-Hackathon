# Requirements and test list (16 audit items + full system)

Every item below must be **tested** and **working**. If a test fails, fix the implementation until it passes.

---

## 1. Test suite exists and runs
- **Test deps:** `pytest`, `pytest-asyncio`, `httpx` (in root `requirements.txt`). Run: `pytest tests/ -v`
- [ ] `tests/` directory with pytest
- [ ] `pytest tests/ -v` runs and all tests pass
- [ ] API tests: route, order, helpstral, flystral, test-frame, health, config, estimate

## 2. WebSocket hardening
- [ ] Malformed JSON on WS does not disconnect client; server ignores or sends error ack
- [ ] Unknown message type does not raise; server ignores
- [ ] Ping/pong works
- [ ] user_position with valid lat/lng forwarded to connector when connector exists
- [ ] user_arrived sends phase return to connector
- [ ] emergency broadcasts to all clients

## 3. Mission in progress
- [ ] POST /api/order when a mission is already active returns 409 or clear message; does not overwrite
- [ ] Optional: mission_id or "mission_in_progress" in response

## 4. Geofence / bounds
- [ ] Origin and destination validated against configurable bounds (or Paris area)
- [ ] Route/order reject or warn when outside service area
- [ ] GET /api/config or env exposes bounds

## 5. Lat/lng sanity for user_position
- [ ] Server rejects or clamps user_position with lat/lng outside reasonable range (e.g. not 0,0, within bounds)
- [ ] Connector does not receive invalid positions

## 6. Flystral command validation
- [ ] Only whitelisted commands (FOLLOW, AVOID_LEFT, AVOID_RIGHT, CLIMB, HOVER, REPLAN, DESCEND) applied
- [ ] Invalid or unparseable Mistral response does not crash; fallback to FOLLOW|0.5

## 7. Connector exit mid-mission
- [ ] When connector process exits unexpectedly, server broadcasts type "connector_died" or "mission_failed"
- [ ] Partner UI shows "Connection lost" or "Mission failed" when this event received
- [ ] _current_mission can be cleared or marked failed so user can order again

## 8. User closes tab / no position timeout
- [ ] Connector or server: after N minutes with no user_position in escort, optionally trigger return or alert
- [ ] Documented behaviour

## 9. Geolocation denied (user app)
- [ ] User app shows clear "Location denied" or "Enable location" state when geolocation fails or is unavailable
- [ ] Live tracking does not silently do nothing; user sees message

## 10. Retries / backoff (optional but recommended)
- [ ] Route (OSRM/ORS) retry with backoff or at least 2 attempts before fallback
- [ ] Helpstral/Flystral: one retry on 5xx or timeout

## 11. Rate limiting (optional)
- [ ] /api/helpstral and /api/flystral rate limit per IP or per session (e.g. 10/min)
- [ ] WS: throttle user_position if needed (server-side)

## 12. Windows connector stdin
- [ ] Live-follow loop works on Windows (threading or polling fallback when select not available)
- [ ] Test or document: "Unix only" vs "Windows supported"

## 13. Deployment
- [ ] Dockerfile builds and runs server
- [ ] /health returns 200 and optionally checks (e.g. config loaded, mission dir writable)
- [ ] README deployment section: how to run with Docker, env vars

## 14. Observability
- [ ] Structured logging (JSON or key=value) for critical actions (order, mission_start, emergency, helpstral/flystral)
- [ ] Or at least consistent log format for debugging

## 15. Config API / adaptability
- [ ] GET /api/config returns public config: hub, bounds, price_per_km, track_alt, etc. (no secrets)
- [ ] User app can show "Service area: Paris" or price info from config

## 16. Pricing and charging (user-facing)
- [ ] Price estimate based on distance (e.g. price_per_km * distance_km + base)
- [ ] GET /api/estimate?origin=lat,lng&destination=lat,lng or POST with origin/dest returns { distance_km, estimate_eur, currency }
- [ ] User app shows estimate before or after route; shows distance
- [ ] Optional: mock "payment" or "Pay €X" button that calls POST /api/payment (mock) and enables "Start mission"

## 17. Simulated battery (drone/partner)
- [ ] When SITL or no real battery: connector or server injects simulated battery_pct that drains over time/distance
- [ ] Partner UI shows battery %; low battery warning at e.g. 15%
- [ ] Telemetry consistently includes battery_pct (real or simulated)

## 18. User app: mobile polish and Mistral UX
- [ ] Mobile viewport and touch targets; bottom sheet usable on phone
- [ ] Mistral used for something user-facing: e.g. "Ask Louise" (route safety summary), or ETA/safety tips from general model
- [ ] Route summary or reassurance message from Mistral (optional but "AI ability" improvement)

## 19. E2E or scripted flow test
- [ ] Script or Playwright: load user app → set route → order → (optional start mission) → send user_position → user_arrived → assert UI or WS events
- [ ] Or pytest with TestClient + async WS client that simulates the flow

## 20. All 16 audit items verified
- [ ] Re-run audit list: tests, WS harden, mission-in-progress, geofence, lat/lng, Flystral validation, connector_died, timeout, geo denied, retries, rate limit, Windows, deploy, observability, config API, pricing, battery sim, user Mistral, e2e.
