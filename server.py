"""
Louise -- safety drone escort system.
Run: uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path so sibling imports work
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    BASE_PRICE_EUR,
    CURRENCY,
    DRONE_HUB,
    FLYSTRAL_MODEL_ID,
    GEOFENCE_BOUNDS,
    HELPSTRAL_MODEL_ID,
    MAV_CONNECTION,
    MISTRAL_API_KEY,
    ORS_API_KEY,
    ORS_BASE_URL,
    OSRM_BASE_URL,
    PRICE_PER_KM_EUR,
    SITL_HOST,
    SITL_PORT,
    TRACK_ALT,
    _env_warnings,
)
from autopilot_adapter.waypoint_generator import generate_from_osrm, generate_all, save_mission, haversine as wp_haversine
from flystral.command_parser import VALID_COMMANDS as FLYSTRAL_VALID_COMMANDS, parse_to_waypoint_update
from helpstral.agent import run_helpstral_agent, get_location_context, DEFAULT_ASSESSMENT as HELPSTRAL_DEFAULT
from flystral.agent import run_flystral_agent, DEFAULT_RESULT as FLYSTRAL_DEFAULT

app = FastAPI(title="Louise API")


def _log_event(event: str, **kwargs):
    """Structured log line for observability (event=value key=value)."""
    parts = [f"event={event}"]
    for k, v in kwargs.items():
        if v is None:
            continue
        parts.append(f"{k}={v!r}" if " " in str(v) else f"{k}={v}")
    print(" ".join(parts), flush=True)


_env_warnings()

# ── Static file serving ────────────────────────────────────────────────────────
Path("autopilot_adapter/output").mkdir(parents=True, exist_ok=True)
app.mount("/autopilot_adapter/output", StaticFiles(directory="autopilot_adapter/output"), name="output")
app.mount("/user", StaticFiles(directory="app/user", html=True), name="user")
app.mount("/partner", StaticFiles(directory="app/partner", html=True), name="partner")


@app.get("/")
async def root():
    return RedirectResponse(url="/user")


# ── WebSocket connection manager ───────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []
        self.sim_task: Optional[asyncio.Task] = None
        self.connector_proc: Optional[asyncio.subprocess.Process] = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def run_sitl_mission(self, connector_path: Path, mission_json: Path, connection: str):
        """
        Run the GUIDED-mode connector as a subprocess and broadcast its JSON stdout.
        Kills MAVProxy first so the connector can take over TCP 5760.
        """
        if self.sim_task and not self.sim_task.done():
            self.sim_task.cancel()

        async def stream_connector():
                global _mission_in_progress
                _mission_in_progress = True
                # Kill MAVProxy so connector can connect to TCP 5760 directly
                # SITL stays running with warm EKF
                kill_proxy = await asyncio.create_subprocess_exec(
                    "pkill", "-f", "mavproxy",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proxy.wait()
                await asyncio.sleep(2)

                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-u",
                    str(connector_path),
                    "--connection", connection,
                    "--mission-json", str(mission_json),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path(__file__).parent),
                )
                manager.connector_proc = proc

                async def relay_stderr():
                    while proc.stderr:
                        line = await proc.stderr.readline()
                        if not line:
                            break
                        text = line.decode().strip()
                        if text:
                            await self.broadcast({"type": "sitl_log", "message": text})

                asyncio.create_task(relay_stderr())

                last_event = None
                try:
                    while proc.stdout:
                        line = await proc.stdout.readline()
                        if not line:
                            break
                        text = line.decode().strip()
                        if not text:
                            continue
                        try:
                            event = json.loads(text)
                            event["source"] = "ardupilot"
                            last_event = event
                            if event.get("type") == "position":
                                _latest_telemetry.update(event)
                            await self.broadcast(event)
                        except json.JSONDecodeError:
                            pass
                except asyncio.CancelledError:
                    if proc.returncode is None:
                        proc.kill()
                    raise
                finally:
                    manager.connector_proc = None
                    _mission_in_progress = False
                    if last_event and last_event.get("type") != "complete":
                        await self.broadcast({"type": "connector_died", "source": "ardupilot"})
                        await self.broadcast({"type": "complete", "source": "ardupilot"})

        self.sim_task = asyncio.create_task(stream_connector())


manager = ConnectionManager()
_current_mission: dict | None = None
_mission_in_progress: bool = False  # True while connector subprocess is running

# ── Agent state (multi-agent loop) ─────────────────────────────────────────────
_assessment_history: list[dict] = []  # sliding window of Helpstral assessments
_latest_helpstral: dict = dict(HELPSTRAL_DEFAULT)
_latest_flystral: dict = dict(FLYSTRAL_DEFAULT)
_latest_telemetry: dict = {}
_latest_user_position: dict = {}
_ASSESSMENT_WINDOW = 10


async def agent_loop(frame_b64: str) -> dict:
    """
    Core multi-agent loop: Helpstral assesses → Flystral decides → execute + broadcast.
    Called every time a frame is available (from partner camera or test-frame).
    """
    global _latest_helpstral, _latest_flystral

    user_pos = _latest_user_position
    location_ctx = get_location_context(
        user_pos.get("lat", DRONE_HUB["lat"]),
        user_pos.get("lng", DRONE_HUB["lng"]),
    ) if user_pos else None

    mission = _current_mission.get("mission") if _current_mission else None
    route_progress = None
    if mission and _latest_telemetry.get("waypoint_index") is not None:
        total = mission["stats"].get("total_waypoints", 1)
        route_progress = _latest_telemetry.get("waypoint_index", 0) / max(1, total)

    helpstral_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: run_helpstral_agent(
            image_b64=frame_b64,
            recent_assessments=_assessment_history[-5:],
            location=location_ctx,
            route_progress=route_progress,
        ),
    )
    _latest_helpstral = helpstral_result
    _assessment_history.append(helpstral_result)
    while len(_assessment_history) > _ASSESSMENT_WINDOW:
        _assessment_history.pop(0)

    flystral_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: run_flystral_agent(
            image_b64=frame_b64,
            threat_assessment=helpstral_result,
            telemetry=_latest_telemetry,
            route_progress=route_progress,
        ),
    )
    _latest_flystral = flystral_result

    command = flystral_result.get("command", "FOLLOW")
    param = str(flystral_result.get("param", "0.5"))
    alt_adjust = flystral_result.get("altitude_adjust", 0)

    if command in FLYSTRAL_VALID_COMMANDS:
        ref = {"lat": 0.0, "lng": 0.0, "alt": 0.0}
        updated = parse_to_waypoint_update(command, param, ref)
        dlat = updated.get("lat", 0.0) - ref["lat"]
        dlng = updated.get("lng", 0.0) - ref["lng"]
        dalt = updated.get("alt", 0.0) - ref["alt"] + alt_adjust
        await _send_to_connector({"type": "flystral_offset", "dlat": dlat, "dlng": dlng, "dalt": dalt})

    await manager.broadcast({
        "type": "agent_update",
        "helpstral": helpstral_result,
        "flystral": flystral_result,
    })

    recent_high_threats = [
        a for a in _assessment_history[-3:]
        if a.get("threat_level", 1) >= 6
    ]
    if len(recent_high_threats) >= 3:
        _log_event("auto_escalation", threat_level=helpstral_result.get("threat_level"),
                   pattern=helpstral_result.get("pattern"))
        await manager.broadcast({
            "type": "emergency",
            "origin": "helpstral_auto_escalation",
            "assessment": helpstral_result,
        })

    return {"helpstral": helpstral_result, "flystral": flystral_result}


def _in_bounds(lat: float, lng: float) -> bool:
    """Check if lat/lng is within GEOFENCE_BOUNDS."""
    b = GEOFENCE_BOUNDS
    return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]


def _clamp_position(lat: float, lng: float) -> tuple[float, float]:
    """Clamp lat/lng to geofence bounds so connector never gets invalid targets."""
    b = GEOFENCE_BOUNDS
    return (
        max(b["lat_min"], min(b["lat_max"], lat)),
        max(b["lng_min"], min(b["lng_max"], lng)),
    )


async def _send_to_connector(obj: dict) -> bool:
    """Send a JSON line to the connector stdin (for live follow). Returns True if sent."""
    proc = manager.connector_proc
    if proc is None or proc.returncode is not None or proc.stdin is None:
        return False
    try:
        proc.stdin.write((json.dumps(obj) + "\n").encode())
        await proc.stdin.drain()
        return True
    except (BrokenPipeError, ConnectionResetError, OSError):
        return False


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    if _current_mission is not None:
        await ws.send_json(_current_mission["broadcast"])
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                await ws.send_json({"type": "error", "message": "Invalid JSON"})
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif msg.get("type") == "user_position" and isinstance(msg.get("lat"), (int, float)) and isinstance(msg.get("lng"), (int, float)):
                lat, lng = _clamp_position(float(msg["lat"]), float(msg["lng"]))
                _latest_user_position.update({"lat": lat, "lng": lng})
                await _send_to_connector({"type": "user_position", "lat": lat, "lng": lng})
            elif msg.get("type") == "user_arrived":
                await _send_to_connector({"type": "phase", "phase": "return"})
            elif msg.get("type") == "emergency":
                _log_event("emergency", origin=msg.get("origin"))
                await manager.broadcast({"type": "emergency", "origin": msg.get("origin")})
            # unknown types ignored (no disconnect)
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── Request / response models ──────────────────────────────────────────────────
class RouteRequest(BaseModel):
    origin: list[float]       # [lat, lng]
    destination: list[float]  # [lat, lng]


class OrderRequest(BaseModel):
    origin: list[float]
    destination: list[float]
    route: Optional[list[list[float]]] = None  # ORS polyline coords [[lng, lat], ...]


class HelpstralRequest(BaseModel):
    image: str  # base64-encoded image


class FlystralRequest(BaseModel):
    image: str  # base64-encoded image


@app.get("/api/config")
async def get_config():
    """Public config for clients: hub, service area, pricing, track altitude. No secrets."""
    return {
        "hub": DRONE_HUB,
        "bounds": GEOFENCE_BOUNDS,
        "track_alt_m": TRACK_ALT,
        "base_price_eur": BASE_PRICE_EUR,
        "price_per_km_eur": PRICE_PER_KM_EUR,
        "currency": CURRENCY,
    }


@app.post("/api/estimate")
async def get_estimate(req: RouteRequest):
    """Return distance (km) and price estimate for a route. Used by user app before ordering."""
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    if not _in_bounds(lat1, lng1) or not _in_bounds(lat2, lng2):
        raise HTTPException(status_code=400, detail="Origin or destination outside service area.")
    distance_m = wp_haversine(lat1, lng1, lat2, lng2)
    distance_km = round(distance_m / 1000.0, 2)
    estimate_eur = round(BASE_PRICE_EUR + distance_km * PRICE_PER_KM_EUR, 2)
    return {
        "distance_km": distance_km,
        "distance_m": int(distance_m),
        "estimate_eur": estimate_eur,
        "currency": CURRENCY,
    }


# Minimal 1x1 grey JPEG for test/placeholder feed (e.g. when no real camera)
_TEST_FRAME_B64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="


@app.get("/api/test-frame", response_class=Response)
async def get_test_frame():
    """
    Return a minimal JPEG image for use as a placeholder when no real drone camera feed is available.
    Partner app can fetch this and use it for Helpstral/Flystral so vision APIs still run.
    """
    return Response(content=base64.b64decode(_TEST_FRAME_B64), media_type="image/jpeg")


# ── /api/route ─────────────────────────────────────────────────────────────────
def _straight_line_coords(lat1: float, lng1: float, lat2: float, lng2: float, num_points: int = 25) -> list:
    """Return [[lng, lat], ...] as a straight line between the two points (for fallback when routing fails)."""
    return [
        [lng1 + (lng2 - lng1) * i / (num_points - 1), lat1 + (lat2 - lat1) * i / (num_points - 1)]
        for i in range(num_points)
    ]


@app.post("/api/route")
async def get_route(req: RouteRequest):
    """
    Get a walking route via OSRM (free), then ORS if key set, then straight-line fallback.
    Returns coords as [[lng, lat], ...]. Always returns coords so the user can proceed.
    If origin or destination is outside geofence, returns 400.
    """
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    if not _in_bounds(lat1, lng1) or not _in_bounds(lat2, lng2):
        raise HTTPException(status_code=400, detail="Origin or destination is outside the service area.")

    # Primary: OSRM public server (1 req/sec limit; use User-Agent)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            url = f"{OSRM_BASE_URL}/foot/{lng1},{lat1};{lng2},{lat2}?overview=full&geometries=geojson"
            resp = await client.get(
                url,
                headers={"User-Agent": "LouiseWalkHome/1.0 (safety escort demo)"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("routes") and len(data["routes"]) > 0:
                route = data["routes"][0]
                coords = route["geometry"]["coordinates"]
                if coords and len(coords) >= 2:
                    return {
                        "coords": coords,
                        "distance_m": route.get("distance"),
                        "duration_s": route.get("duration"),
                        "points": len(coords),
                        "source": "osrm",
                    }
    except Exception:
        pass

    # Fallback: ORS (needs API key)
    if ORS_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{ORS_BASE_URL}/directions/foot-walking/geojson",
                    headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
                    json={"coordinates": [[lng1, lat1], [lng2, lat2]]},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("features") and len(data["features"]) > 0:
                    coords = data["features"][0]["geometry"]["coordinates"]
                    if coords:
                        return {"coords": coords, "source": "ors", "points": len(coords)}
        except Exception:
            pass

    # Always return a usable route: straight line so the user can continue
    coords = _straight_line_coords(lat1, lng1, lat2, lng2)
    dist = wp_haversine(lat1, lng1, lat2, lng2)
    return {
        "coords": coords,
        "distance_m": int(dist),
        "duration_s": int(dist / 1.2),
        "points": len(coords),
        "source": "fallback",
        "detail": "Routing service busy or unavailable; showing straight line. You can still request a drone.",
    }


# ── /api/order — plan the mission (no simulation yet) ──────────────────────────
@app.post("/api/order")
async def order_drone(req: OrderRequest):
    """
    Generate ArduPilot waypoint files for all 3 phases and broadcast to Mission Control.
    The route from the user app (OSRM walking polyline) is used directly as escort waypoints
    so the drone follows the exact walking route, not a straight line.
    Returns 409 if a mission is already in progress (connector running).
    """
    global _current_mission
    if _mission_in_progress:
        raise HTTPException(status_code=409, detail="A mission is already in progress. Wait for it to finish or reconnect.")
    hub = (DRONE_HUB["lat"], DRONE_HUB["lng"])
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    if not _in_bounds(lat1, lng1) or not _in_bounds(lat2, lng2):
        raise HTTPException(status_code=400, detail="Origin or destination is outside the service area. Please choose locations within the supported region.")

    route_coords = req.route
    if route_coords and len(route_coords) >= 2:
        print(f"[order] Using {len(route_coords)} route coords from user app", flush=True)
        mission = generate_from_osrm(hub, route_coords)
    else:
        print("[order] No route coords from user app, fetching from OSRM", flush=True)
        lat1, lng1 = req.origin
        lat2, lng2 = req.destination
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                url = f"{OSRM_BASE_URL}/foot/{lng1},{lat1};{lng2},{lat2}?overview=full&geometries=geojson"
                resp = await client.get(
                    url,
                    headers={"User-Agent": "LouiseWalkHome/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("routes") and data["routes"][0]["geometry"]["coordinates"]:
                    route_coords = data["routes"][0]["geometry"]["coordinates"]
                    print(f"[order] Fetched {len(route_coords)} route coords from OSRM", flush=True)
                    mission = generate_from_osrm(hub, route_coords)
                else:
                    raise ValueError("No route from OSRM")
        except Exception as e:
            print(f"[order] OSRM failed ({e}), using straight line fallback", flush=True)
            user = tuple(req.origin)
            dest = tuple(req.destination)
            walking_route = [(user[0] + (dest[0]-user[0])*t/20, user[1] + (dest[1]-user[1])*t/20) for t in range(21)]
            mission = generate_all(hub, user, walking_route, dest)

    out_dir = Path("autopilot_adapter/output")
    files = save_mission(mission, out_dir)

    approach_wps = mission["approach"]
    approach_dist = sum(
        wp_haversine(approach_wps[i]["lat"], approach_wps[i]["lng"],
                     approach_wps[i+1]["lat"], approach_wps[i+1]["lng"])
        for i in range(len(approach_wps) - 1)
    ) if len(approach_wps) > 1 else 0
    approach_eta_s = round(approach_dist / 8)  # cruise speed 8 m/s

    routes = {
        "approach": [[w["lat"], w["lng"]] for w in mission["approach"]],
        "escort": [[w["lat"], w["lng"]] for w in mission["escort"]],
        "return": [[w["lat"], w["lng"]] for w in mission["return"]],
    }

    broadcast_msg = {
        "type": "mission_update",
        "routes": routes,
        "stats": mission["stats"],
        "hub": DRONE_HUB,
        "user": mission["user"],
        "destination": mission["destination"],
        "approach_eta_s": approach_eta_s,
        "files": files,
    }

    _current_mission = {
        "mission": mission,
        "files": files,
        "broadcast": broadcast_msg,
    }

    await manager.broadcast(broadcast_msg)
    _log_event("mission_planned", waypoints=mission["stats"].get("total_waypoints"), hub_lat=DRONE_HUB["lat"])

    return {
        "status": "planned",
        "hub": DRONE_HUB,
        "stats": mission["stats"],
        "approach_eta_s": approach_eta_s,
        "files": files,
        "routes": routes,
    }


# ── /api/mission/start — begin ArduPilot SITL flight ───────────────────────────
@app.post("/api/mission/start")
async def start_mission_endpoint():
    """
    Start the real ArduPilot SITL flight for the planned mission.
    Auto-starts SITL if it's not already running (waits up to 90s).
    The mavlink_connector uploads waypoints, arms, takes off, flies AUTO,
    and streams real MAVLink telemetry back to all WebSocket clients.
    """
    if _current_mission is None:
        raise HTTPException(status_code=400, detail="No mission planned. Call POST /api/order first.")

    use_real_drone = MAV_CONNECTION is not None and MAV_CONNECTION.strip() != ""

    if not use_real_drone:
        # Start SITL if not already running
        sitl_running = await _check_sitl_running()
        if not sitl_running:
            await manager.broadcast({"type": "sitl_status", "status": "starting"})
            await sitl_start()
            for _ in range(45):
                await asyncio.sleep(2)
                if await _check_sitl_running():
                    sitl_running = True
                    break
            if not sitl_running:
                raise HTTPException(status_code=503, detail="SITL did not start in time.")

        # Wait for EKF warmup before flying
        await manager.broadcast({"type": "sitl_status", "status": "warming_up"})
        if not await _wait_for_sitl_ready(timeout=90):
            await manager.broadcast({"type": "sitl_log", "message": "WARNING: EKF warmup timeout, proceeding anyway"})

    await manager.broadcast({"type": "sitl_status", "status": "running"})

    out_dir = Path("autopilot_adapter/output")
    connector_path = Path(__file__).parent / "autopilot_adapter" / "mavlink_connector.py"
    mission_json_path = out_dir / "mission.json"
    connection = (MAV_CONNECTION or "").strip() or f"tcp:{SITL_HOST}:{SITL_PORT}"

    if not connector_path.exists():
        raise HTTPException(status_code=500, detail="mavlink_connector.py not found.")
    if not mission_json_path.exists():
        raise HTTPException(status_code=500, detail="mission.json not found. Call /api/order first.")

    await manager.run_sitl_mission(connector_path, mission_json_path, connection)
    await manager.broadcast({"type": "mission_started", "source": "ardupilot"})

    mission = _current_mission["mission"]
    total = len(mission["approach"]) + len(mission["escort"]) + len(mission["return"])
    _log_event("mission_start", waypoints=total)
    return {"status": "started", "source": "ardupilot", "waypoints": total}


async def _kill_existing_sitl():
    """Kill any running SITL and MAVProxy so next launch starts fresh at the hub."""
    if manager.sim_task and not manager.sim_task.done():
        manager.sim_task.cancel()
    for name in ["arducopter", "mavproxy"]:
        p = await asyncio.create_subprocess_exec(
            "pkill", "-f", name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await p.wait()
    global _sitl_process
    _sitl_process = None
    await asyncio.sleep(2)


async def _check_sitl_running() -> bool:
    """Check if ArduCopter SITL process is running."""
    check_script = (
        "import subprocess, sys; "
        "r = subprocess.run(['pgrep', '-f', 'arducopter.*--model'], capture_output=True); "
        "sys.exit(0 if r.returncode == 0 else 1)"
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", check_script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(Path(__file__).parent),
        )
        await asyncio.wait_for(proc.wait(), timeout=6.0)
        return proc.returncode == 0
    except (asyncio.TimeoutError, Exception):
        return False


async def _wait_for_sitl_ready(timeout: float = 90) -> bool:
    """Wait for SITL EKF to converge by checking MAVProxy logs."""
    log_path = Path("autopilot_adapter/output/sitl.log")
    start = time.time()
    while time.time() - start < timeout:
        if log_path.exists():
            text = log_path.read_text()
            if "EKF3 IMU0 is using GPS" in text and "EKF3 IMU1 is using GPS" in text:
                return True
        await asyncio.sleep(2)
    return await _check_sitl_running()


# ── /api/helpstral ────────────────────────────────────────────────────────────
@app.post("/api/helpstral")
async def helpstral(req: HelpstralRequest):
    """
    Run Helpstral structured safety assessment on a base64 image.
    Returns full structured assessment: threat_level, status, observations, pattern, reasoning, action.
    """
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: run_helpstral_agent(
            image_b64=req.image,
            recent_assessments=_assessment_history[-5:],
            location=get_location_context(
                _latest_user_position.get("lat", DRONE_HUB["lat"]),
                _latest_user_position.get("lng", DRONE_HUB["lng"]),
            ),
        ),
    )
    global _latest_helpstral
    _latest_helpstral = result
    _assessment_history.append(result)
    while len(_assessment_history) > _ASSESSMENT_WINDOW:
        _assessment_history.pop(0)
    return result


# ── /api/flystral ─────────────────────────────────────────────────────────────
@app.post("/api/flystral")
async def flystral(req: FlystralRequest):
    """
    Run Flystral structured flight command on a base64 drone camera image.
    Uses latest Helpstral assessment for threat-aware flight decisions.
    Returns full structured command: command, param, reasoning, altitude_adjust, etc.
    """
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: run_flystral_agent(
            image_b64=req.image,
            threat_assessment=_latest_helpstral,
            telemetry=_latest_telemetry,
        ),
    )
    global _latest_flystral
    _latest_flystral = result

    command = result.get("command", "FOLLOW")
    param = str(result.get("param", "0.5"))
    alt_adjust = result.get("altitude_adjust", 0)

    await manager.broadcast({"type": "flystral", "command": command, "param": param})

    if command in FLYSTRAL_VALID_COMMANDS:
        ref = {"lat": 0.0, "lng": 0.0, "alt": 0.0}
        updated = parse_to_waypoint_update(command, param, ref)
        dlat = updated.get("lat", 0.0) - ref["lat"]
        dlng = updated.get("lng", 0.0) - ref["lng"]
        dalt = updated.get("alt", 0.0) - ref["alt"] + alt_adjust
        await _send_to_connector({"type": "flystral_offset", "dlat": dlat, "dlng": dlng, "dalt": dalt})

    return result


# ── /api/agent-loop — full multi-agent cycle ──────────────────────────────────
@app.post("/api/agent-loop")
async def run_agent_loop(req: HelpstralRequest):
    """
    Run the full multi-agent loop: Helpstral → Flystral → execute + broadcast.
    Returns both agent results. Used by partner app for coordinated AI cycle.
    """
    return await agent_loop(req.image)


# ── ArduPilot SITL control (for Mission Control UI) ─────────────────────────────
_sitl_process: Optional[subprocess.Popen] = None


@app.post("/api/sitl/start")
async def sitl_start():
    """
    Start ArduPilot SITL in the background so Mission Control can run the live demo
    without opening a terminal. SITL may take 30–90s to be ready; poll /api/sitl/status.
    """
    global _sitl_process
    if _sitl_process is not None and _sitl_process.poll() is None:
        return {"status": "already_running", "message": "SITL is already starting or running."}

    project_root = Path(__file__).parent
    start_script = project_root / "start_sitl.sh"
    if not start_script.exists():
        raise HTTPException(status_code=500, detail="start_sitl.sh not found.")

    # Write SITL home from config so start_sitl.sh uses same hub as missions (Louvre)
    out_dir = project_root / "autopilot_adapter" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    home_file = out_dir / "sitl_home.txt"
    home_file.write_text(f"{DRONE_HUB['lat']},{DRONE_HUB['lng']},35.0,0.0")

    log_path = out_dir / "sitl.log"
    try:
        with open(log_path, "w") as logf:
            _sitl_process = subprocess.Popen(
                ["/bin/bash", str(start_script)],
                cwd=str(project_root),
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**subprocess.os.environ},
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "starting",
        "message": "SITL is starting. Poll GET /api/sitl/status until running (may take 30–90s).",
        "log_file": str(log_path),
    }


@app.get("/api/sitl/status")
async def sitl_status():
    """Return whether ArduPilot SITL is reachable on UDP 14550."""
    return {"running": await _check_sitl_running()}


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    out_dir = Path("autopilot_adapter/output")
    output_writable = False
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".health_probe"
        probe.write_text("")
        probe.unlink(missing_ok=True)
        output_writable = True
    except Exception:
        pass
    return {
        "status": "ok",
        "mistral_key": bool(MISTRAL_API_KEY),
        "ors_key": bool(ORS_API_KEY),
        "helpstral_model": HELPSTRAL_MODEL_ID,
        "flystral_model": FLYSTRAL_MODEL_ID,
        "output_writable": output_writable,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
