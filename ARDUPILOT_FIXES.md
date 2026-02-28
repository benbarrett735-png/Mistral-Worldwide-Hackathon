# ArduPilot integration — why it wasn’t working and what was fixed

## Critical assessment: why the system wasn’t working

### 1. Drone starting in the wrong place (“North Paris”)

**Cause:** SITL home and mission home can get out of sync.

- **SITL home** is set only when the simulator starts (`start_sitl.sh` with `--home lat,lon,alt,heading`). If SITL was started manually or by another script with a different `--home`, the sim starts somewhere else (e.g. a default or “North Paris”).
- **Mission waypoints** are built from `config.DRONE_HUB` (Louvre) when the user orders a drone. So the mission is always Louvre-centric.
- If SITL was started with a different home, the vehicle appears at that wrong position and the route on the map doesn’t match.

**Fix:**

- **Single source of truth for home:** Before starting SITL, the server writes `autopilot_adapter/output/sitl_home.txt` from `config.DRONE_HUB` (Louvre). `start_sitl.sh` reads this file and passes it to `--home`. So whenever the server starts SITL, it always starts at the same hub as the missions.
- **If you start SITL yourself:** Run `./start_sitl.sh` from the project root so it picks up `sitl_home.txt`, or the script falls back to Louvre. Do not start ArduCopter with a different `--home` if you want the drone to match the map and routes.

### 2. Drone not actually flying the route (point to point)

**Cause:** After GUIDED takeoff we switched to AUTO without telling the autopilot *which* mission item to run next.

- Mission layout: item 0 = home, 1 = takeoff, 2 = speed, 3+ = route (approach → escort → return), last = RTL.
- We uploaded the mission, did a GUIDED takeoff to 10 m, then set mode AUTO. AUTO then started from item 0 (home). The vehicle was already at home and at altitude, so it could advance through 0, 1, 2 and then the route, but behaviour was implicit and could be inconsistent (e.g. lingering or wrong “current” item).

**Fix:**

- After takeoff and before setting AUTO, we now send **MISSION_SET_CURRENT** with sequence **3** (first route waypoint). Then we set mode AUTO. So the sim explicitly flies from waypoint 3 onward along the route (approach → escort → return), then RTL. The software is now clearly “flying from point to point along the routes.”

### 3. Summary of code changes

| Component | Change |
|----------|--------|
| **server.py** | When starting SITL, write `autopilot_adapter/output/sitl_home.txt` from `DRONE_HUB` (lat,lon,35.0,0.0) so `start_sitl.sh` uses it. |
| **start_sitl.sh** | Read `autopilot_adapter/output/sitl_home.txt` if present and use it for `--home`; otherwise use default Louvre. |
| **mavlink_connector.py** | After GUIDED takeoff, call `mission_set_current_send(..., 3)` so AUTO runs from the first route waypoint, then set mode AUTO. |

## How to get correct behaviour

1. **Start SITL from the app** (Mission Control “Start SITL” or let the server auto-start on first mission). That uses `sitl_home.txt` and matches the missions.
2. **Or** run from project root: `./start_sitl.sh` — same file is used.
3. **Do not** start ArduCopter manually with a different `--home` if you want the drone to start at the Louvre and follow the planned routes.

After these fixes, the ArduPilot sim starts at the configured hub (Louvre) and flies the uploaded route waypoint-by-waypoint, then returns to launch.
