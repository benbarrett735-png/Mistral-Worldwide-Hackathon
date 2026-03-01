"""
Louise -- safety drone escort system.
Run: uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import uuid
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
    CITY_HUBS,
    CURRENCY,
    DEFAULT_CITY,
    DRONE_HUB,
    FLYSTRAL_ENDPOINT,
    GEOFENCE_BOUNDS,
    HELPSTRAL_ENDPOINT,
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
from flystral.command_parser import (
    VALID_COMMANDS as FLYSTRAL_VALID_COMMANDS,
    parse_to_waypoint_update,
    parse_velocity_output,
)
from helpstral.agent import (
    run_helpstral_agent, get_location_context, DEFAULT_ASSESSMENT as HELPSTRAL_DEFAULT,
    set_shared_state as helpstral_set_state,
)
from flystral.agent import (
    run_flystral_agent, DEFAULT_RESULT as FLYSTRAL_DEFAULT,
    set_shared_state as flystral_set_state,
)
from louise.agent import run_louise_agent, set_shared_state as louise_set_state

app = FastAPI(title="Louise API")

_sitl_warm = False  # True once SITL is confirmed ready (EKF warm)
_sitl_city: str | None = None  # Which city SITL is currently positioned at


@app.on_event("startup")
async def _prewarm_sitl():
    """Kick off SITL pre-warm in background so server starts accepting requests immediately."""
    use_real = MAV_CONNECTION is not None and MAV_CONNECTION.strip() != ""
    if use_real:
        global _sitl_warm
        _sitl_warm = True
        return
    asyncio.create_task(_do_prewarm_sitl())


async def _do_prewarm_sitl():
    """Background task: start SITL and wait for it to be ready."""
    global _sitl_warm, _sitl_city
    _log_event("sitl_prewarm_start")
    already = await _check_sitl_running()
    if not already:
        try:
            await sitl_start(city=DEFAULT_CITY)
        except Exception:
            _log_event("sitl_prewarm_failed")
            return
    for _ in range(40):
        await asyncio.sleep(1.5)
        if await _check_sitl_running():
            _sitl_warm = True
            _sitl_city = DEFAULT_CITY
            _log_event("sitl_prewarm_done", city=DEFAULT_CITY)
            return
    _log_event("sitl_prewarm_timeout")


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
        if not self.connections:
            return
        async def _safe_send(ws):
            try:
                await asyncio.wait_for(ws.send_json(data), timeout=5.0)
                return None
            except Exception:
                return ws
        results = await asyncio.gather(*[_safe_send(ws) for ws in self.connections])
        for ws in results:
            if ws is not None:
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
                start_autonomous_agent_loop()
                kill_proxy = await asyncio.create_subprocess_exec(
                    "pkill", "-f", "mavproxy",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await kill_proxy.wait()
                await asyncio.sleep(0.5)

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

                # Feed demo user positions (escort waypoints at walking speed)
                # so SITL's live_follow_loop has positions to track
                async def feed_demo_positions():
                    await asyncio.sleep(5)  # wait for approach to start
                    mission_data = _current_mission.get("mission", {}) if _current_mission else {}
                    escort_wps = mission_data.get("escort", [])
                    if not escort_wps:
                        return
                    # Wait until approach is done (phase changes to escort)
                    for _ in range(300):  # max 5 min wait
                        if _latest_telemetry.get("phase") == "escort":
                            break
                        await asyncio.sleep(1)
                    else:
                        return

                    WALK_SPEED = 1.4  # m/s
                    for i, wp in enumerate(escort_wps):
                        if proc.returncode is not None:
                            return
                        msg = json.dumps({"type": "user_position", "lat": wp["lat"], "lng": wp["lng"]}) + "\n"
                        try:
                            proc.stdin.write(msg.encode())
                            await proc.stdin.drain()
                        except (BrokenPipeError, OSError):
                            return
                        await self.broadcast({"type": "user_position", "lat": wp["lat"], "lng": wp["lng"], "source": "demo"})

                        if i + 1 < len(escort_wps):
                            seg_dist = wp_haversine(wp["lat"], wp["lng"], escort_wps[i+1]["lat"], escort_wps[i+1]["lng"])
                            delay = max(1.0, min(seg_dist / WALK_SPEED, 5.0))
                            await asyncio.sleep(delay)

                    # Demo user arrived at destination
                    last_wp = escort_wps[-1] if escort_wps else {}
                    await self.broadcast({
                        "type": "user_arrived", "auto": True,
                        "timestamp": time.time(),
                        "lat": last_wp.get("lat"), "lng": last_wp.get("lng"),
                    })
                    _log_event("user_arrived", auto=True, source="demo")

                    try:
                        proc.stdin.write((json.dumps({"type": "phase", "phase": "return"}) + "\n").encode())
                        await proc.stdin.drain()
                    except (BrokenPipeError, OSError):
                        pass

                asyncio.create_task(feed_demo_positions())

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
                    stop_autonomous_agent_loop()
                    mid = _current_mission.get("mission_id", "") if _current_mission else ""
                    if mid in _missions_history:
                        _missions_history[mid].update(status="completed", ended_at=time.time())
                    if last_event and last_event.get("type") != "complete":
                        await self.broadcast({"type": "connector_died", "source": "ardupilot"})
                        await self.broadcast({"type": "complete", "source": "ardupilot"})

        self.sim_task = asyncio.create_task(stream_connector())


manager = ConnectionManager()
_current_mission: dict | None = None
_mission_in_progress: bool = False
_mission_lock = asyncio.Lock()
_missions_history: dict[str, dict] = {}  # mission_id -> mission summary

def _http_client(**kwargs) -> httpx.AsyncClient:
    """Reusable HTTP client with sensible defaults."""
    defaults = {"timeout": 15, "headers": {"User-Agent": "LouiseWalkHome/1.0"}}
    defaults.update(kwargs)
    return httpx.AsyncClient(**defaults)

# ── Agent state (multi-agent loop) ─────────────────────────────────────────────
_assessment_history: list[dict] = []  # sliding window of Helpstral assessments
_latest_helpstral: dict = dict(HELPSTRAL_DEFAULT)
_latest_flystral: dict = dict(FLYSTRAL_DEFAULT)
_latest_telemetry: dict = {}
_latest_user_position: dict = {}
_ASSESSMENT_WINDOW = 10


def _sync_shared_state():
    """Push latest server state into agent modules so their tools return live data."""
    helpstral_set_state(_assessment_history, _latest_user_position)

    mission = _current_mission.get("mission") if _current_mission else None
    route_progress = None
    if mission and _latest_telemetry.get("waypoint_index") is not None:
        total = mission["stats"].get("total_waypoints", 1)
        route_progress = _latest_telemetry.get("waypoint_index", 0) / max(1, total)

    flystral_set_state(_latest_telemetry, _latest_helpstral, route_progress)
    louise_set_state(
        {
            "active": _mission_in_progress,
            "phase": _latest_telemetry.get("phase", "idle"),
            "battery_pct": _latest_telemetry.get("battery_pct"),
            "distance_to_user": _latest_telemetry.get("distance_to_user"),
            "threat_level": _latest_helpstral.get("threat_level", 1),
        },
        _latest_user_position,
    )
    return route_progress


async def agent_loop(frame_b64: str) -> dict:
    """
    Core multi-agent loop: Helpstral assesses (with tool calling) →
    Flystral decides (with tool calling) → execute + broadcast.
    Both agents use Mistral function calling to query live state.
    """
    global _latest_helpstral, _latest_flystral

    route_progress = _sync_shared_state()

    helpstral_result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: run_helpstral_agent(
            image_b64=frame_b64,
            recent_assessments=_assessment_history[-5:],
            route_progress=route_progress,
        ),
    )
    _latest_helpstral = helpstral_result
    _assessment_history.append(helpstral_result)
    while len(_assessment_history) > _ASSESSMENT_WINDOW:
        _assessment_history.pop(0)

    _sync_shared_state()

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

    flystral_mode = flystral_result.get("mode", "discrete")

    if flystral_mode == "velocity":
        offset = flystral_result.get("offset", {})
        await _send_to_connector({
            "type": "flystral_offset",
            "dlat": offset.get("dlat", 0),
            "dlng": offset.get("dlng", 0),
            "dalt": offset.get("dalt", 0),
            "dyaw": offset.get("dyaw", 0),
            "velocity": {
                "vx": flystral_result.get("vx", 0),
                "vy": flystral_result.get("vy", 0),
                "vz": flystral_result.get("vz", 0),
                "yaw_rate": flystral_result.get("yaw_rate", 0),
            },
        })
    else:
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

    hs_tools = helpstral_result.get("tool_calls_made", [])
    fs_tools = flystral_result.get("tool_calls_made", [])
    await manager.broadcast({
        "type": "agent_update",
        "helpstral": helpstral_result,
        "flystral": flystral_result,
        "flystral_mode": flystral_mode,
        "tools_used": {
            "helpstral": [t["tool"] for t in hs_tools],
            "flystral": [t["tool"] for t in fs_tools],
        },
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


# ── Autonomous agent background loop ────────────────────────────────────────
_agent_loop_task: asyncio.Task | None = None
AGENT_LOOP_INTERVAL_S = 5


async def _autonomous_agent_loop():
    """
    Runs continuously while a mission is active. Every AGENT_LOOP_INTERVAL_S seconds,
    fetches a frame (from test-frame or camera) and runs the full agent loop.
    """
    _log_event("autonomous_agent_loop", status="started")
    try:
        while _mission_in_progress:
            try:
                frame_b64 = _latest_camera_frame or _TEST_FRAME_B64
                await agent_loop(frame_b64)
            except Exception as e:
                _log_event("agent_loop_error", error=str(e))
            await asyncio.sleep(AGENT_LOOP_INTERVAL_S)
    except asyncio.CancelledError:
        pass
    finally:
        _log_event("autonomous_agent_loop", status="stopped")


def start_autonomous_agent_loop():
    """Start the background agent loop (called when mission starts)."""
    global _agent_loop_task
    if _agent_loop_task and not _agent_loop_task.done():
        return
    _agent_loop_task = asyncio.create_task(_autonomous_agent_loop())


def stop_autonomous_agent_loop():
    """Stop the background agent loop (called when mission ends)."""
    global _agent_loop_task
    if _agent_loop_task and not _agent_loop_task.done():
        _agent_loop_task.cancel()
    _agent_loop_task = None


def _get_city_bounds(city: str | None = None) -> dict:
    """Get geofence bounds for a city, falling back to default."""
    if city and city in CITY_HUBS:
        return CITY_HUBS[city]["bounds"]
    return GEOFENCE_BOUNDS


def _get_city_hub(city: str | None = None) -> dict:
    """Get hub coords for a city, falling back to default."""
    if city and city in CITY_HUBS:
        return CITY_HUBS[city]["hub"]
    return DRONE_HUB


def _in_bounds(lat: float, lng: float, city: str | None = None) -> bool:
    """Check if lat/lng is within geofence bounds (city-aware)."""
    b = _get_city_bounds(city)
    return b["lat_min"] <= lat <= b["lat_max"] and b["lng_min"] <= lng <= b["lng_max"]


def _clamp_position(lat: float, lng: float, city: str | None = None) -> tuple[float, float]:
    """Clamp lat/lng to geofence bounds so connector never gets invalid targets."""
    b = _get_city_bounds(city)
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
                auto = msg.get("auto", False)
                _log_event("user_arrived", auto=auto)
                await manager.broadcast({
                    "type": "user_arrived",
                    "auto": auto,
                    "timestamp": time.time(),
                    "lat": _latest_user_position.get("lat"),
                    "lng": _latest_user_position.get("lng"),
                })
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
    city: Optional[str] = None


class OrderRequest(BaseModel):
    origin: list[float]
    destination: list[float]
    route: Optional[list[list[float]]] = None  # ORS polyline coords [[lng, lat], ...]
    city: Optional[str] = None


class EmergencyRequest(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    origin: Optional[list[float]] = None
    reasoning: Optional[str] = None


@app.post("/api/emergency")
async def emergency_http(req: EmergencyRequest):
    """HTTP fallback for emergency alerts (when WebSocket is down)."""
    lat = req.lat or (req.origin[0] if req.origin and len(req.origin) >= 2 else None)
    lng = req.lng or (req.origin[1] if req.origin and len(req.origin) >= 2 else None)
    payload = {
        "type": "emergency",
        "lat": lat, "lng": lng,
        "reasoning": req.reasoning or "User triggered emergency",
        "source": "http_fallback",
        "timestamp": time.time(),
    }
    await manager.broadcast(payload)
    _log_event("emergency", lat=lat, lng=lng, source="http")
    return {"status": "emergency_sent", "message": "Alert broadcast to all connected stations"}


class HelpstralRequest(BaseModel):
    image: str  # base64-encoded image


class FlystralRequest(BaseModel):
    image: str  # base64-encoded image


class LouiseRequest(BaseModel):
    message: str
    conversation: list[dict] = []


@app.get("/api/config")
async def get_config():
    """Public config for clients: cities with hubs, service areas, pricing, track altitude."""
    return {
        "hub": DRONE_HUB,
        "bounds": GEOFENCE_BOUNDS,
        "track_alt_m": TRACK_ALT,
        "base_price_eur": BASE_PRICE_EUR,
        "price_per_km_eur": PRICE_PER_KM_EUR,
        "currency": CURRENCY,
        "cities": {k: {"name": v["name"], "hub": v["hub"], "center": v["center"],
                        "bounds": v["bounds"], "country": v["country"],
                        "viewbox": v["viewbox"], "zoom": v["zoom"]}
                   for k, v in CITY_HUBS.items()},
    }


@app.post("/api/estimate")
async def get_estimate(req: RouteRequest):
    """Return distance (km) and price estimate using OSRM walking route distance (not straight-line)."""
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    if not _in_bounds(lat1, lng1, req.city) or not _in_bounds(lat2, lng2, req.city):
        raise HTTPException(status_code=400, detail="Origin or destination outside service area.")

    # Use real walking route distance from OSRM, fall back to straight-line
    route_distance_m = None
    try:
        async with _http_client() as client:
            url = f"{OSRM_BASE_URL}/foot/{lng1},{lat1};{lng2},{lat2}?overview=false"
            resp = await client.get(url, headers={"User-Agent": "LouiseWalkHome/1.0"})
            resp.raise_for_status()
            data = resp.json()
            if data.get("routes"):
                route_distance_m = data["routes"][0].get("distance")
    except Exception:
        pass

    if route_distance_m is None:
        route_distance_m = wp_haversine(lat1, lng1, lat2, lng2)

    city_hub = _get_city_hub(req.city)
    hub_lat, hub_lng = city_hub["lat"], city_hub["lng"]
    approach_m = wp_haversine(hub_lat, hub_lng, lat1, lng1)
    return_m = wp_haversine(lat2, lng2, hub_lat, hub_lng)
    total_flight_m = approach_m + route_distance_m + return_m

    distance_km = round(route_distance_m / 1000.0, 2)
    distance_price = round(distance_km * PRICE_PER_KM_EUR, 2)
    total_eur = round(BASE_PRICE_EUR + distance_price, 2)

    return {
        "distance_km": distance_km,
        "distance_m": int(route_distance_m),
        "estimate_eur": total_eur,
        "base_price_eur": BASE_PRICE_EUR,
        "distance_price_eur": distance_price,
        "total_flight_distance_m": int(total_flight_m),
        "currency": CURRENCY,
        "pricing_note": f"Base fee {CURRENCY} {BASE_PRICE_EUR:.2f} + {CURRENCY} {PRICE_PER_KM_EUR:.2f}/km walking distance",
    }


# Minimal 1x1 grey JPEG for test/placeholder feed (e.g. when no real camera)
_TEST_FRAME_B64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
_latest_camera_frame: str | None = None  # latest base64 JPEG from drone camera


class CameraFrameRequest(BaseModel):
    image_b64: str


@app.post("/api/camera/frame")
async def post_camera_frame(req: CameraFrameRequest):
    """Accept a base64 JPEG frame from the drone camera. Used by companion computer or test harness."""
    global _latest_camera_frame
    _latest_camera_frame = req.image_b64
    return {"status": "ok", "size": len(req.image_b64)}


@app.get("/api/camera/latest", response_class=Response)
async def get_latest_camera_frame():
    """Return the latest camera frame as JPEG (for Mission Control display)."""
    frame = _latest_camera_frame or _TEST_FRAME_B64
    return Response(content=base64.b64decode(frame), media_type="image/jpeg")


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


_route_cache: dict[str, dict] = {}

def _price_from_distance(distance_m: float, origin: tuple, dest: tuple) -> dict:
    """Compute pricing from route distance."""
    distance_km = round(distance_m / 1000.0, 2)
    distance_price = round(distance_km * PRICE_PER_KM_EUR, 2)
    total_eur = round(BASE_PRICE_EUR + distance_price, 2)
    sym = "\u20AC" if CURRENCY == "EUR" else CURRENCY
    return {
        "estimate_eur": total_eur,
        "base_price_eur": BASE_PRICE_EUR,
        "distance_price_eur": distance_price,
        "distance_km": distance_km,
        "currency": CURRENCY,
        "pricing_note": f"Base {sym}{BASE_PRICE_EUR:.2f} + {sym}{PRICE_PER_KM_EUR:.2f}/km x {distance_km}km",
    }


@app.post("/api/route")
async def get_route(req: RouteRequest):
    """
    Get a pedestrian walking route + pricing in one call.
    Priority: ORS foot-walking (best pedestrian paths) → OSRM foot → straight-line.
    Returns coords as [[lng, lat], ...] plus price estimate. Always returns coords.
    """
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    if not _in_bounds(lat1, lng1, req.city) or not _in_bounds(lat2, lng2, req.city):
        raise HTTPException(status_code=400, detail="Origin or destination is outside the service area.")

    cache_key = f"{req.city or 'default'}:{lat1:.5f},{lng1:.5f}-{lat2:.5f},{lng2:.5f}"
    if cache_key in _route_cache:
        return _route_cache[cache_key]

    result = None

    # Try ORS first — best pedestrian routing (parks, footpaths, stairs, pedestrian zones)
    if ORS_API_KEY:
        try:
            async with _http_client() as client:
                resp = await client.post(
                    f"{ORS_BASE_URL}/directions/foot-walking/geojson",
                    headers={"Authorization": ORS_API_KEY, "Content-Type": "application/json"},
                    json={"coordinates": [[lng1, lat1], [lng2, lat2]]},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("features") and len(data["features"]) > 0:
                    feat = data["features"][0]
                    coords = feat["geometry"]["coordinates"]
                    props = feat.get("properties", {}).get("summary", {})
                    if coords and len(coords) >= 2:
                        dist_m = props.get("distance") or wp_haversine(lat1, lng1, lat2, lng2)
                        result = {
                            "coords": coords,
                            "distance_m": props.get("distance"),
                            "duration_s": props.get("duration"),
                            "points": len(coords),
                            "source": "ors",
                            "price": _price_from_distance(dist_m, req.origin, req.destination),
                        }
        except Exception:
            pass

    # Fallback: OSRM foot profile
    if result is None:
        try:
            async with _http_client() as client:
                url = f"{OSRM_BASE_URL}/foot/{lng1},{lat1};{lng2},{lat2}?overview=full&geometries=geojson&steps=true&continue_straight=true&alternatives=false"
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                if data.get("routes") and len(data["routes"]) > 0:
                    route = data["routes"][0]
                    coords = route["geometry"]["coordinates"]
                    if coords and len(coords) >= 2:
                        dist_m = route.get("distance") or wp_haversine(lat1, lng1, lat2, lng2)
                        result = {
                            "coords": coords,
                            "distance_m": route.get("distance"),
                            "duration_s": route.get("duration"),
                            "points": len(coords),
                            "source": "osrm",
                            "price": _price_from_distance(dist_m, req.origin, req.destination),
                        }
        except Exception:
            pass

    if result is None:
        coords = _straight_line_coords(lat1, lng1, lat2, lng2)
        dist = wp_haversine(lat1, lng1, lat2, lng2)
        result = {
            "coords": coords,
            "distance_m": int(dist),
            "duration_s": int(dist / 1.2),
            "points": len(coords),
            "source": "fallback",
            "detail": "Routing service busy; showing straight line. You can still request a drone.",
            "price": _price_from_distance(dist, req.origin, req.destination),
        }

    _route_cache[cache_key] = result
    if len(_route_cache) > 100:
        oldest = next(iter(_route_cache))
        del _route_cache[oldest]
    return result


# ── /api/order — plan the mission (no simulation yet) ──────────────────────────
@app.post("/api/order")
async def order_drone(req: OrderRequest):
    """
    Generate ArduPilot waypoint files for all 3 phases and broadcast to Mission Control.
    The route from the user app (OSRM walking polyline) is used directly as escort waypoints
    so the drone follows the exact walking route, not a straight line.
    Auto-cancels any in-progress mission before planning the new one.
    """
    global _current_mission, _mission_in_progress
    async with _mission_lock:
        if _mission_in_progress:
            await _force_cancel_mission()
    city_hub = _get_city_hub(req.city)
    hub = (city_hub["lat"], city_hub["lng"])
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    if not _in_bounds(lat1, lng1, req.city) or not _in_bounds(lat2, lng2, req.city):
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
            async with _http_client() as client:
                url = f"{OSRM_BASE_URL}/foot/{lng1},{lat1};{lng2},{lat2}?overview=full&geometries=geojson&steps=true&continue_straight=true"
                resp = await client.get(url)
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
    approach_eta_s = round(approach_dist / 50)  # approach at 50 m/s

    routes = {
        "approach": [[w["lat"], w["lng"]] for w in mission["approach"]],
        "escort": [[w["lat"], w["lng"]] for w in mission["escort"]],
        "return": [[w["lat"], w["lng"]] for w in mission["return"]],
    }

    broadcast_msg = {
        "type": "mission_update",
        "routes": routes,
        "stats": mission["stats"],
        "hub": city_hub,
        "user": mission["user"],
        "destination": mission["destination"],
        "approach_eta_s": approach_eta_s,
        "files": files,
        "city": req.city,
    }

    mission_id = str(uuid.uuid4())[:8]
    _current_mission = {
        "mission_id": mission_id,
        "mission": mission,
        "files": files,
        "broadcast": broadcast_msg,
        "status": "planned",
        "created_at": time.time(),
        "city": req.city,
    }
    broadcast_msg["mission_id"] = mission_id

    _missions_history[mission_id] = {
        "mission_id": mission_id,
        "status": "planned",
        "created_at": time.time(),
        "origin": list(req.origin),
        "destination": list(req.destination),
        "stats": mission["stats"],
    }

    await manager.broadcast({
        "type": "position",
        "lat": city_hub["lat"], "lng": city_hub["lng"], "alt": 0,
        "phase": "idle", "source": "hub_reset",
    })
    await manager.broadcast(broadcast_msg)
    _log_event("mission_planned", mission_id=mission_id, waypoints=mission["stats"].get("total_waypoints"), hub_lat=city_hub["lat"])

    # Calculate accurate price from mission waypoint distances
    escort_wps = mission["escort"]
    escort_dist = sum(
        wp_haversine(escort_wps[i]["lat"], escort_wps[i]["lng"],
                     escort_wps[i+1]["lat"], escort_wps[i+1]["lng"])
        for i in range(len(escort_wps) - 1)
    ) if len(escort_wps) > 1 else 0
    escort_km = round(escort_dist / 1000.0, 2)
    price_eur = round(BASE_PRICE_EUR + escort_km * PRICE_PER_KM_EUR, 2)

    return {
        "status": "planned",
        "hub": city_hub,
        "stats": mission["stats"],
        "approach_eta_s": approach_eta_s,
        "files": files,
        "routes": routes,
        "price": {
            "total_eur": price_eur,
            "base_eur": BASE_PRICE_EUR,
            "distance_eur": round(escort_km * PRICE_PER_KM_EUR, 2),
            "escort_distance_km": escort_km,
            "currency": CURRENCY,
        },
    }


# ── /api/mission/start — begin flight (ArduPilot SITL always, mock fallback) ──
@app.post("/api/mission/start")
async def start_mission_endpoint():
    """
    Start the mission flight. Always uses ArduPilot SITL.
    - If MAV_CONNECTION is set: uses real drone hardware directly
    - Otherwise: starts ArduPilot SITL if not already running
    - Falls back to mock simulator only if ArduCopter binary not found
    """
    global _sitl_warm, _sitl_city
    if _current_mission is None:
        raise HTTPException(status_code=400, detail="No mission planned. Call POST /api/order first.")

    use_real_drone = MAV_CONNECTION is not None and MAV_CONNECTION.strip() != ""
    mission_city = _current_mission.get("city") or DEFAULT_CITY

    if not use_real_drone:
        # If SITL is running for a different city, kill it and restart at the correct hub
        if _sitl_city and _sitl_city != mission_city and await _check_sitl_running():
            _log_event("sitl_city_mismatch", was=_sitl_city, need=mission_city)
            await manager.broadcast({"type": "sitl_status", "status": "relocating"})
            await _kill_existing_sitl()
            _sitl_warm = False

        sitl_running = _sitl_warm or await _check_sitl_running()
        if not sitl_running:
            try:
                await manager.broadcast({"type": "sitl_status", "status": "starting"})
                await sitl_start(city=mission_city)
                for _ in range(15):
                    await asyncio.sleep(1)
                    if await _check_sitl_running():
                        sitl_running = True
                        break
            except Exception as e:
                _log_event("sitl_start_failed", error=str(e))

            if not sitl_running:
                _log_event("sitl_fallback_to_mock")
                return await _start_mock_mission()

        if _sitl_warm and _sitl_city == mission_city:
            await manager.broadcast({"type": "sitl_status", "status": "running"})
        else:
            await manager.broadcast({"type": "sitl_status", "status": "warming_up"})
            if not await _wait_for_sitl_ready(timeout=20):
                await manager.broadcast({"type": "sitl_log", "message": "EKF warmup timeout — proceeding"})
            _sitl_warm = True
            _sitl_city = mission_city

    await manager.broadcast({"type": "sitl_status", "status": "running"})
    out_dir = Path("autopilot_adapter/output")
    connector_path = Path(__file__).parent / "autopilot_adapter" / "mavlink_connector.py"
    mission_json_path = out_dir / "mission.json"
    connection = (MAV_CONNECTION or "").strip() or f"tcp:{SITL_HOST}:{SITL_PORT}"

    if not connector_path.exists():
        raise HTTPException(status_code=500, detail="mavlink_connector.py not found.")
    if not mission_json_path.exists():
        raise HTTPException(status_code=500, detail="mission.json not found.")

    await manager.run_sitl_mission(connector_path, mission_json_path, connection)
    await manager.broadcast({"type": "mission_started", "source": "ardupilot"})
    mission = _current_mission["mission"]
    total = len(mission["approach"]) + len(mission["escort"]) + len(mission["return"])
    mid = _current_mission.get("mission_id", "")
    if mid in _missions_history:
        _missions_history[mid].update(status="active", started_at=time.time())
    _log_event("mission_start", mission_id=mid, waypoints=total, mode="ardupilot")
    return {"status": "started", "source": "ardupilot", "waypoints": total, "mission_id": mid}


async def _start_mock_mission():
    """Run the mock simulator with phase-aware speeds as a background task."""
    global _mission_in_progress
    from autopilot_adapter.mock_simulator import simulate_mission

    mission = _current_mission["mission"]
    total = len(mission["approach"]) + len(mission["escort"]) + len(mission["return"])

    async def run_mock():
        global _mission_in_progress
        _mission_in_progress = True
        start_autonomous_agent_loop()
        try:
            async def on_event(event):
                event["source"] = "mock"
                if event.get("type") == "position":
                    _latest_telemetry.update(event)
                elif event.get("type") == "user_position":
                    _latest_user_position.update({"lat": event["lat"], "lng": event["lng"]})
                await manager.broadcast(event)

            await simulate_mission(mission, on_event)
        finally:
            _mission_in_progress = False
            stop_autonomous_agent_loop()
            mid = _current_mission.get("mission_id", "") if _current_mission else ""
            if mid in _missions_history:
                _missions_history[mid].update(status="completed", ended_at=time.time())

    if manager.sim_task and not manager.sim_task.done():
        manager.sim_task.cancel()
    manager.sim_task = asyncio.create_task(run_mock())
    await manager.broadcast({"type": "mission_started", "source": "mock"})
    mid = _current_mission.get("mission_id", "")
    if mid in _missions_history:
        _missions_history[mid].update(status="active", started_at=time.time())
    _log_event("mission_start", mission_id=mid, waypoints=total, mode="mock")
    return {"status": "started", "source": "mock", "waypoints": total, "mission_id": mid}


async def _force_cancel_mission():
    """Forcefully cancel any running mission — kill connector, reset state."""
    global _mission_in_progress
    if manager.sim_task and not manager.sim_task.done():
        manager.sim_task.cancel()
        try:
            await manager.sim_task
        except (asyncio.CancelledError, Exception):
            pass
    if hasattr(manager, 'connector_proc') and manager.connector_proc and manager.connector_proc.returncode is None:
        manager.connector_proc.kill()
    _mission_in_progress = False
    stop_autonomous_agent_loop()
    mid = _current_mission.get("mission_id", "") if _current_mission else ""
    if mid in _missions_history:
        _missions_history[mid].update(status="cancelled", ended_at=time.time())
    _log_event("mission_cancelled", mission_id=mid)


@app.post("/api/mission/cancel")
async def cancel_mission():
    """Cancel any running mission."""
    if not _mission_in_progress:
        return {"status": "no_mission"}
    async with _mission_lock:
        await _force_cancel_mission()
    return {"status": "cancelled"}


@app.get("/api/mission/status")
async def mission_status():
    """Get current mission state, progress, and phase."""
    if not _current_mission:
        return {"status": "idle", "active": False}

    mission = _current_mission.get("mission", {})
    stats = mission.get("stats", {})
    total = stats.get("total_waypoints", 0)
    current_wp = _latest_telemetry.get("waypoint_index", 0) or 0
    progress = round(current_wp / max(1, total) * 100)

    return {
        "status": "active" if _mission_in_progress else "planned",
        "active": _mission_in_progress,
        "phase": _latest_telemetry.get("phase", "idle"),
        "progress_pct": progress,
        "waypoint": current_wp,
        "total_waypoints": total,
        "battery_pct": _latest_telemetry.get("battery_pct"),
        "ground_speed": _latest_telemetry.get("ground_speed"),
        "altitude": _latest_telemetry.get("alt"),
        "threat_level": _latest_helpstral.get("threat_level", 1),
        "threat_status": _latest_helpstral.get("status", "SAFE"),
        "mission_id": _current_mission.get("mission_id", "") if _current_mission else "",
    }


@app.get("/api/missions")
async def list_missions():
    """List all missions (active + historical) for Mission Control overview."""
    missions = []
    for mid, m in _missions_history.items():
        entry = dict(m)
        if _current_mission and _current_mission.get("mission_id") == mid and _mission_in_progress:
            entry["status"] = "active"
            entry["phase"] = _latest_telemetry.get("phase", "idle")
            entry["battery_pct"] = _latest_telemetry.get("battery_pct")
            entry["ground_speed"] = _latest_telemetry.get("ground_speed")
        missions.append(entry)
    missions.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return {"missions": missions, "total": len(missions)}


async def _kill_existing_sitl():
    """Kill any running SITL and MAVProxy so next launch starts fresh at the hub."""
    global _sitl_process, _sitl_warm, _sitl_city
    if manager.sim_task and not manager.sim_task.done():
        manager.sim_task.cancel()
    for name in ["arducopter", "mavproxy"]:
        p = await asyncio.create_subprocess_exec(
            "pkill", "-f", name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await p.wait()
    _sitl_process = None
    _sitl_warm = False
    _sitl_city = None
    await asyncio.sleep(0.5)


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
        await asyncio.wait_for(proc.wait(), timeout=3.0)
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
        await asyncio.sleep(1)
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

    flystral_mode = result.get("mode", "discrete")

    if flystral_mode == "velocity":
        offset = result.get("offset", {})
        await manager.broadcast({
            "type": "flystral",
            "mode": "velocity",
            "vx": result.get("vx", 0),
            "vy": result.get("vy", 0),
            "vz": result.get("vz", 0),
            "yaw_rate": result.get("yaw_rate", 0),
        })
        await _send_to_connector({
            "type": "flystral_offset",
            "dlat": offset.get("dlat", 0),
            "dlng": offset.get("dlng", 0),
            "dalt": offset.get("dalt", 0),
            "dyaw": offset.get("dyaw", 0),
        })
    else:
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


# ── /api/louise — Ask Louise conversational agent ─────────────────────────────
@app.post("/api/louise")
async def ask_louise(req: LouiseRequest):
    """
    Ask Louise: user-facing conversational AI with tool calling.
    Louise can query route safety, escort status, area info, and safety tips.
    """
    _sync_shared_state()
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: run_louise_agent(req.message, req.conversation),
    )
    return result


# ── /api/agent-status — what the agents are doing right now ───────────────────
@app.get("/api/agent-status")
async def agent_status():
    """Return current agent state: latest assessments, tools used, loop active."""
    return {
        "loop_active": _agent_loop_task is not None and not _agent_loop_task.done(),
        "mission_active": _mission_in_progress,
        "helpstral": _latest_helpstral,
        "flystral": _latest_flystral,
        "assessment_history_size": len(_assessment_history),
    }


# ── ArduPilot SITL control (for Mission Control UI) ─────────────────────────────
_sitl_process: Optional[subprocess.Popen] = None


@app.post("/api/sitl/start")
async def sitl_start_endpoint():
    """HTTP endpoint wrapper for sitl_start."""
    return await sitl_start()


async def sitl_start(city: str | None = None):
    """
    Start ArduPilot SITL at the hub for the given city.
    """
    global _sitl_process, _sitl_city
    if _sitl_process is not None and _sitl_process.poll() is None:
        return {"status": "already_running", "message": "SITL is already starting or running."}

    hub = _get_city_hub(city)

    project_root = Path(__file__).parent
    start_script = project_root / "start_sitl.sh"
    if not start_script.exists():
        raise HTTPException(status_code=500, detail="start_sitl.sh not found.")

    out_dir = project_root / "autopilot_adapter" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    home_file = out_dir / "sitl_home.txt"
    home_file.write_text(f"{hub['lat']},{hub['lng']},35.0,0.0")
    _sitl_city = city

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


# ── /api/route-safety — fast safety score for route card ──────────────────────
class RouteSafetyRequest(BaseModel):
    origin: list[float]
    destination: list[float]


@app.post("/api/route-safety")
async def route_safety(req: RouteSafetyRequest):
    """
    Fast safety check for a route: samples the midpoint and destination
    for streetlight density, lit roads, and POIs from real OSM data.
    Returns a composite score + brief summary without requiring Mistral.
    """
    lat1, lng1 = req.origin
    lat2, lng2 = req.destination
    try:
        from geo_intel import compute_area_safety_score
        mid_lat = (lat1 + lat2) / 2
        mid_lng = (lng1 + lng2) / 2
        mid = await asyncio.get_event_loop().run_in_executor(
            None, lambda: compute_area_safety_score(mid_lat, mid_lng)
        )
        dest = await asyncio.get_event_loop().run_in_executor(
            None, lambda: compute_area_safety_score(lat2, lng2)
        )
        avg = round((mid["safety_score"] + dest["safety_score"]) / 2)
        avg = max(1, min(10, avg))

        if avg >= 7:
            summary = "Well-lit route with good foot traffic"
            level = "good"
        elif avg >= 5:
            summary = "Moderate lighting — drone escort recommended"
            level = "moderate"
        else:
            summary = "Low lighting & foot traffic — escort strongly recommended"
            level = "poor"

        return {
            "score": avg,
            "level": level,
            "summary": summary,
            "lighting": mid.get("lighting_quality", "unknown"),
            "foot_traffic": mid.get("foot_traffic_level", "unknown"),
            "streetlights": mid.get("streetlights_nearby", 0) + dest.get("streetlights_nearby", 0),
            "neighborhood": mid.get("neighborhood", "Unknown"),
        }
    except Exception:
        return {"score": 5, "level": "moderate", "summary": "Safety data unavailable", "lighting": "unknown"}


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
        "helpstral_model": "BenBarr/helpstral" if HELPSTRAL_ENDPOINT else "pixtral-12b-2409",
        "flystral_model": "BenBarr/flystral" if FLYSTRAL_ENDPOINT else "ministral-3b-latest",
        "output_writable": output_writable,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
