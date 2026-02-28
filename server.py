"""
Louise -- safety drone escort system.
Run: uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path so sibling imports work
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    DRONE_HUB,
    FLYSTROLL_MODEL_ID,
    HELPSTROLL_MODEL_ID,
    MISTRAL_API_KEY,
    ORS_API_KEY,
    ORS_BASE_URL,
)
from autopilot_adapter.waypoint_generator import generate_from_ors_route, generate_all
from autopilot_adapter.mock_simulator import simulate_async, load_waypoints
from flystroll.command_parser import apply_command

app = FastAPI(title="Louise API")

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

    async def run_simulation(self, waypoints: list[dict]):
        """Start the drone sim as a background task, broadcasting to all clients."""
        if self.sim_task and not self.sim_task.done():
            self.sim_task.cancel()

        flystroll_counter = 0

        async def broadcast_event(event: dict):
            nonlocal flystroll_counter
            await self.broadcast(event)

            # Every 5 position events during the track phase, emit a mock Flystroll command
            if event.get("type") == "position" and event.get("phase") == "track":
                flystroll_counter += 1
                if flystroll_counter % 5 == 0:
                    # Mock Flystroll without a real image (demo mode)
                    demo_commands = [
                        {"command": "FOLLOW", "param": "0.7"},
                        {"command": "FOLLOW", "param": "0.5"},
                        {"command": "AVOID_LEFT", "param": "2"},
                        {"command": "FOLLOW", "param": "0.8"},
                        {"command": "HOVER", "param": "2"},
                    ]
                    cmd = demo_commands[(flystroll_counter // 5 - 1) % len(demo_commands)]
                    await self.broadcast({
                        "type": "flystroll",
                        "command": cmd["command"],
                        "param": cmd["param"],
                        "source": "demo",
                    })

        self.sim_task = asyncio.create_task(simulate_async(waypoints, broadcast_event))


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive; client can send pings or control messages
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
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


class HelpstrollRequest(BaseModel):
    image: str  # base64-encoded image


class FlystrollRequest(BaseModel):
    image: str  # base64-encoded image


# ── /api/route ─────────────────────────────────────────────────────────────────
@app.post("/api/route")
async def get_route(req: RouteRequest):
    """
    Get a walking route from OpenRouteService.
    Returns a GeoJSON polyline of [lng, lat] coordinates.
    Falls back to a straight line if ORS is unavailable or no API key.
    """
    if not ORS_API_KEY:
        # Demo fallback: straight line divided into segments
        lat1, lng1 = req.origin
        lat2, lng2 = req.destination
        coords = [
            [lng1 + (lng2 - lng1) * t / 8, lat1 + (lat2 - lat1) * t / 8]
            for t in range(9)
        ]
        return {"coords": coords, "source": "straight_line"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{ORS_BASE_URL}/directions/foot-walking/geojson",
                headers={
                    "Authorization": ORS_API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "coordinates": [
                        [req.origin[1], req.origin[0]],       # ORS wants [lng, lat]
                        [req.destination[1], req.destination[0]],
                    ]
                },
            )
            resp.raise_for_status()
            data = resp.json()
            coords = data["features"][0]["geometry"]["coordinates"]  # [[lng, lat], ...]
            return {"coords": coords, "source": "ors"}
    except Exception as e:
        # Fallback if ORS fails
        lat1, lng1 = req.origin
        lat2, lng2 = req.destination
        coords = [
            [lng1 + (lng2 - lng1) * t / 8, lat1 + (lat2 - lat1) * t / 8]
            for t in range(9)
        ]
        return {"coords": coords, "source": "fallback", "error": str(e)}


# ── /api/order ─────────────────────────────────────────────────────────────────
@app.post("/api/order")
async def order_drone(req: OrderRequest):
    """
    Generate waypoint files for all 3 flight phases and kick off the sim.
    Returns waypoint summary and starts broadcasting position updates via WS.
    """
    hub = (DRONE_HUB["lat"], DRONE_HUB["lng"])

    if req.route and len(req.route) >= 2:
        mission = generate_from_ors_route(hub, req.route)
    else:
        user = tuple(req.origin)
        dest = tuple(req.destination)
        # Simple 4-point route between origin and destination
        walking_route = [
            (user[0] + (dest[0] - user[0]) * t / 3,
             user[1] + (dest[1] - user[1]) * t / 3)
            for t in range(4)
        ]
        mission = generate_all(hub, user, walking_route, dest)

    # Save mission files
    out_dir = Path("autopilot_adapter/output")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "mission.json", "w") as f:
        json.dump({
            "hub_to_user": mission["hub_to_user"],
            "track": mission["track"],
            "home": mission["home"],
        }, f)
    with open(out_dir / "mission.plan", "w") as f:
        json.dump(mission["qgc_plan"], f, indent=2)

    # Start simulation (broadcasts via WebSocket)
    all_waypoints = mission["hub_to_user"] + mission["track"] + mission["home"]
    await manager.run_simulation(all_waypoints)

    return {
        "status": "dispatched",
        "hub": DRONE_HUB,
        "waypoints": {
            "hub_to_user": len(mission["hub_to_user"]),
            "track": len(mission["track"]),
            "home": len(mission["home"]),
        },
        "routes": {
            "hub_to_user": [[w["lat"], w["lng"]] for w in mission["hub_to_user"]],
            "track": [[w["lat"], w["lng"]] for w in mission["track"]],
            "home": [[w["lat"], w["lng"]] for w in mission["home"]],
        },
    }


# ── /api/helpstroll ────────────────────────────────────────────────────────────
@app.post("/api/helpstroll")
async def helpstroll(req: HelpstrollRequest):
    """
    Run Helpstroll distress detection on a base64 image.
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
            model=HELPSTROLL_MODEL_ID,
            messages=messages,
            max_tokens=10,
        )
        raw = response.choices[0].message.content.strip().upper()
        status = "DISTRESS" if "DISTRESS" in raw else "SAFE"
        return {"status": status, "raw": raw}

    except Exception as e:
        return {"status": "SAFE", "error": str(e)}


# ── /api/flystroll ─────────────────────────────────────────────────────────────
@app.post("/api/flystroll")
async def flystroll(req: FlystrollRequest):
    """
    Run Flystroll vision-to-command on a base64 drone camera image.
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
            model=FLYSTROLL_MODEL_ID,
            messages=messages,
            max_tokens=20,
        )
        raw = response.choices[0].message.content.strip()
        parts = raw.split("|")
        command = parts[0].upper() if parts else "FOLLOW"
        param = parts[1] if len(parts) > 1 else "0.5"
        return {"command": command, "param": param, "raw": raw}

    except Exception as e:
        return {"command": "FOLLOW", "param": "0.5", "error": str(e)}


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mistral_key": bool(MISTRAL_API_KEY),
        "ors_key": bool(ORS_API_KEY),
        "helpstroll_model": HELPSTROLL_MODEL_ID,
        "flystroll_model": FLYSTROLL_MODEL_ID,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
