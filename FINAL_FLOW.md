# Helpstral & Flystral — Final Flow Specification

## App Split

| App | Platform | Purpose |
|-----|----------|---------|
| **User app** | Phone (web) | Request escort, enter route, track drone |
| **Partner app** | Laptop | Mission control, camera feed, waypoint status, Helpstral overlay |

---

## User App Flow

### 1. Login
- User logs in on phone (we'll add auth; for 48h demo, can dummy this).

### 2. "Walk me home"
- User taps **"Walk me home"**.

### 3. Enter route
- **Origin:** Live from device GPS (`navigator.geolocation`)
- **Destination:** User enters where they're going (address or map picker)
- **Interface:** Google Maps–style — origin + destination, route between them
- **Use dummy data** for demo where needed, but **real location API** in place

### 4. Route display
- App shows walking route (A → B), distance, ETA.

### 5. Order drone
- User taps **"Order drone"**.
- Drone arrives within a few minutes (from Paris hub).

---

## Drone Flight Flow

### Phase 1: Hub → User
- **Start:** Paris hub (fixed location).
- **End:** User's current location.
- **Output:** Waypoint file (hub → user).
- Drone flies to user.

### Phase 2: Track user along route
- Drone flies **along the user's pre-planned walking route**.
- Matches **user's walking speed** (stays in sync).
- **Camera swivels** to keep user in frame.
- **Normally:** Stays on pre-planned path.
- **If user deviates:** **Flystral takes over** — tracks user, follows them off-path.
- **Output:** Waypoint file for route + live updates when Flystral intervenes.

### Phase 3: Obstacle avoidance (in-flight)
- Drone flies **lower** when escorting (not as high as approach).
- May encounter: power lines, trees, buildings.
- **Flystral:** On-demand waypoint changes to avoid obstacles.
- Approach: fly higher to avoid lines, drop down to person; escort: lower altitude.

### Phase 4: Fly home
- User reaches destination.
- **Output:** Waypoint file (destination → hub).
- Drone flies home on predetermined route.

---

## Waypoint Generation

| Segment | Input | Output |
|---------|-------|--------|
| **Hub → User** | Hub coords, user location | Waypoint file (KMZ/MAVLink) |
| **Track user** | User's walking route | Waypoint file + live Flystral edits |
| **Home** | Destination coords, hub coords | Waypoint file |

**Best approach:** Use 3D map (building heights) + pathfinding. Output format: MAVLink or KMZ for ArduPilot.

**Live updates:** Flystral can inject new waypoints during flight (deviation, obstacle).

---

## Flystral Role (Summary)

- **Pre-flight:** Generate waypoint files for hub→user, track, home.
- **In-flight takeover when:**
  1. **User deviates** from route → track and follow user.
  2. **Obstacle** (power line, etc.) → adjust waypoints to avoid.
  3. **Emergency** → get closer, different behavior if needed.

---

## Mission Control (Partner App, Laptop)

### What they see
1. **Order alert** — Someone pressed "Order drone".
2. **Waypoint status:**
   - Hub → User: **Complete**
   - Track user: **Complete** (or "Live" when Flystral editing)
   - Home: **Complete**
3. **Live camera feed** — From drone, watching the person walk.
4. **Helpstral overlay** — Only flags when distress detected.

### Layout
- Map with routes (hub→user, track, home).
- Status badges: Complete / In progress / Live.
- Camera feed panel.
- Helpstral indicator (green = safe, red = distress).

---

## Map / Routing Stack (Open Source)

| Need | Option |
|------|--------|
| **Map display** | Leaflet + OpenStreetMap, or MapLibre (3D) |
| **Routing** | OpenRouteService (free API), OSRM, or GraphHopper |
| **Directions** | Walking profile, returns polyline waypoints |
| **Geocoding** | Nominatim (OSM) or OpenRouteService |

**Preferred:** Open source — Leaflet, OSRM or OpenRouteService for routing.

---

## Data Flow Summary

```
USER APP                          BACKEND / FLYSTROLL              PARTNER APP
────────                          ─────────────────               ────────────
Login
  │
Walk me home
  │
Location (GPS) ──────────────────►
  │
Destination (pick) ──────────────►
  │
Route (A→B walking) ◄──────────── OpenRouteService / OSRM
  │
Order drone ─────────────────────► Generate: Hub→User waypoints
                                    Generate: Track waypoints
                                    Generate: Home waypoints
  │                                    │
  │                                    ├─────────────────────────► Mission Control
  │                                    │                            - Routes populate
  │                                    │                            - Status: complete
  │                                    │                            - Camera feed
  │                                    │                            - Helpstral overlay
  │
Drone flies ◄─────────────────────── ArduPilot (waypoints)
  │
Flystral (live) ◄───────────────── Obstacle / deviation → new waypoints
  │
Helpstral ◄─────────────────────── Camera → distress check → flag if needed
```

---

## 48h Demo Scope

| Feature | Demo? | Notes |
|---------|-------|-------|
| User login | Skip or dummy | Single "Demo user" |
| Location from device | ✅ | Real `navigator.geolocation` |
| Destination picker | ✅ | Map click or address |
| Route display | ✅ | Leaflet + OpenRouteService |
| Order drone | ✅ | Button, triggers backend |
| Waypoint generation | ✅ | Hub→user, track, home (simplified) |
| Mission control UI | ✅ | Status, map, camera placeholder |
| Live camera feed | ⚠️ | Simulated or placeholder |
| Helpstral overlay | ✅ | Image upload → distress check |
| Flystral live edits | ⚠️ | "User deviated" mock flow |

---

## Next Steps

1. Set up repo: `app/user`, `app/partner`, `app/shared` (API).
2. User app: Leaflet map, geolocation, OpenRouteService routing, Order button.
3. Partner app: Mission control layout, waypoint status, camera panel.
4. Backend: Waypoint generation from route + hub + destination.
5. Helpstral: Image → distress API.
6. Flystral: Obstacle/deviation → waypoint update (mock for demo).
