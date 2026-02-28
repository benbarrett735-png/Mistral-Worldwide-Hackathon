"""
Mock drone simulator.
Reads waypoints and emits simulated position updates.
Supports both CLI mode and async callback mode (for WebSocket integration).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Awaitable, Callable

SECONDS_PER_WAYPOINT = 1.5


def load_waypoints(mission_path: Path) -> list[dict]:
    with open(mission_path) as f:
        data = json.load(f)
    return data["hub_to_user"] + data["track"] + data["home"]


def make_position_event(wp: dict, index: int, total: int) -> dict:
    """Build a WebSocket-ready position event dict."""
    phase = wp.get("phase", "unknown")
    return {
        "type": "position",
        "lat": wp["lat"],
        "lng": wp["lng"],
        "alt": wp["alt"],
        "waypoint_index": index,
        "total_waypoints": total,
        "phase": phase,
    }


def make_phase_event(phase: str) -> dict:
    return {"type": "phase", "phase": phase}


async def simulate_async(
    waypoints: list[dict],
    callback: Callable[[dict], Awaitable[None]],
    speed: float = SECONDS_PER_WAYPOINT,
) -> None:
    """
    Async simulation loop. Calls callback with each position event.
    Also emits phase-change events when the flight phase changes.
    Designed to be run as an asyncio task alongside the FastAPI WebSocket server.
    """
    current_phase = None

    for i, wp in enumerate(waypoints):
        phase = wp.get("phase", "unknown")

        if phase != current_phase:
            current_phase = phase
            await callback(make_phase_event(phase))

        await callback(make_position_event(wp, i, len(waypoints)))

        if i < len(waypoints) - 1:
            await asyncio.sleep(speed)

    await callback({"type": "complete"})


def simulate_cli(waypoints: list[dict], speed: float = SECONDS_PER_WAYPOINT) -> None:
    """CLI mode: print JSON lines to stdout."""
    import time
    for i, wp in enumerate(waypoints):
        print(json.dumps(make_position_event(wp, i, len(waypoints))), flush=True)
        if i < len(waypoints) - 1:
            time.sleep(speed)
    print(json.dumps({"type": "complete"}), flush=True)


if __name__ == "__main__":
    mission_file = Path(__file__).parent / "output" / "mission.json"
    if not mission_file.exists():
        print("Run: python waypoint_generator.py first", file=sys.stderr)
        sys.exit(1)

    waypoints = load_waypoints(mission_file)
    print("MOCK_SIM_START", json.dumps({"waypoint_count": len(waypoints)}), flush=True)
    simulate_cli(waypoints)
