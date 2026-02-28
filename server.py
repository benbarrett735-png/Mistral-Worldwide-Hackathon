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
    DRONE_HUB,
    FLYSTRAL_MODEL_ID,
    HELPSTRAL_MODEL_ID,
    MAV_CONNECTION,
    MISTRAL_API_KEY,
    ORS_API_KEY,
    ORS_BASE_URL,
    OSRM_BASE_URL,
    SITL_HOST,
    SITL_PORT,
    _env_warnings,
)
from autopilot_adapter.waypoint_generator import generate_from_osrm, generate_all, save_mission, haversine as wp_haversine
from flystral.command_parser import apply_command, parse_to_waypoint_update

app = FastAPI(title="Louise API")

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
                            await self.broadcast(event)
                        except json.JSONDecodeError:
                            pass
                except asyncio.CancelledError:
                    if proc.returncode is None:
                        proc.kill()
                    raise
                finally:
                    manager.connector_proc = None
                    if last_event and last_event.get("type") != "complete":
                        await self.broadcast({"type": "complete", "source": "ardupilot"})

        self.sim_task = asyncio.create_task(stream_connector())


manager = ConnectionManager()
_current_mission: dict | None = None


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
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif msg.get("type") == "user_position" and isinstance(msg.get("lat"), (int, float)) and isinstance(msg.get("lng"), (int, float)):
                await _send_to_connector({"type": "user_position", "lat": msg["lat"], "lng": msg["lng"]})
            elif msg.get("type") == "user_arrived":
                await _send_to_connector({"type": "phase", "phase": "return"})
            elif msg.get("type") == "emergency":
                await manager.broadcast({"type": "emergency", "origin": msg.get("origin")})
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
    """
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination

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
    """
    global _current_mission
    hub = (DRONE_HUB["lat"], DRONE_HUB["lng"])

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
    Run Helpstral distress detection on a base64 image.
    Returns {"status": "SAFE" | "DISTRESS"}.
    Falls back to SAFE if no API key set.
    """
    if not MISTRAL_API_KEY:
        return {"status": "SAFE", "source": "no_key_fallback"}

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are Louise Vision, a safety AI watching over a person walking alone at night. "
                            "Analyze this image from their surroundings or camera. "
                            "Respond with ONLY one word: DISTRESS (if you see signs of danger, threat, "
                            "struggle, aggression, or the person appears in trouble) or SAFE (if everything appears normal). "
                            "One word only."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{req.image}",
                    },
                ],
            }
        ]

        response = client.chat.complete(
            model=HELPSTRAL_MODEL_ID,
            messages=messages,
            max_tokens=10,
        )
        raw = response.choices[0].message.content.strip().upper()
        status = "DISTRESS" if "DISTRESS" in raw else "SAFE"
        return {"status": status, "raw": raw}

    except Exception as e:
        return {"status": "SAFE", "error": str(e)}


# ── /api/flystral ─────────────────────────────────────────────────────────────
@app.post("/api/flystral")
async def flystral(req: FlystralRequest):
    """
    Run Flystral vision-to-command on a base64 drone camera image.
    Returns {"command": "FOLLOW|0.5"} etc.
    """
    if not MISTRAL_API_KEY:
        return {"command": "FOLLOW", "param": "0.5", "source": "no_key_fallback"}

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are Louise Pilot, an AI autopilot for a safety escort drone. "
                            "Analyze this drone camera image and decide the next flight action. "
                            "Respond with ONLY one of these commands:\n"
                            "FOLLOW|<speed 0.1-1.0> - Follow the person ahead\n"
                            "AVOID_LEFT|<distance> - Obstacle on right, move left\n"
                            "AVOID_RIGHT|<distance> - Obstacle on left, move right\n"
                            "CLIMB|<meters> - Obstacle ahead, climb over\n"
                            "HOVER|<seconds> - Stop and hover briefly\n"
                            "REPLAN|0 - User has deviated, replan route\n"
                            "Example: FOLLOW|0.5\n"
                            "Respond with the command only, nothing else."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{req.image}",
                    },
                ],
            }
        ]

        response = client.chat.complete(
            model=FLYSTRAL_MODEL_ID,
            messages=messages,
            max_tokens=20,
        )
        raw = response.choices[0].message.content.strip()
        parts = raw.split("|")
        command = parts[0].upper() if parts else "FOLLOW"
        param = parts[1] if len(parts) > 1 else "0.5"

        await manager.broadcast({"type": "flystral", "command": command, "param": param})

        ref = {"lat": 0.0, "lng": 0.0, "alt": 0.0}
        updated = parse_to_waypoint_update(command, param, ref)
        dlat = updated.get("lat", 0.0) - ref["lat"]
        dlng = updated.get("lng", 0.0) - ref["lng"]
        dalt = updated.get("alt", 0.0) - ref["alt"]
        await _send_to_connector({"type": "flystral_offset", "dlat": dlat, "dlng": dlng, "dalt": dalt})

        return {"command": command, "param": param, "raw": raw}

    except Exception as e:
        return {"command": "FOLLOW", "param": "0.5", "error": str(e)}


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
    return {
        "status": "ok",
        "mistral_key": bool(MISTRAL_API_KEY),
        "ors_key": bool(ORS_API_KEY),
        "helpstral_model": HELPSTRAL_MODEL_ID,
        "flystral_model": FLYSTRAL_MODEL_ID,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
