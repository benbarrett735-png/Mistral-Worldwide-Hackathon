"""
Mock drone simulator — phase-aware speeds with demo user walking.

Approach: drone zips from hub to user at 50 m/s (very fast, few updates)
Escort:   drone follows at walking pace (~1.4 m/s), emitting position + simulated user position
Return:   instant snap to hub
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Awaitable, Callable


def load_mission(mission_path: Path) -> dict:
    with open(mission_path) as f:
        return json.load(f)


def _haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lat1, lon1, lat2, lon2):
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r)
         - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


async def simulate_mission(
    mission: dict,
    callback: Callable[[dict], Awaitable[None]],
) -> None:
    approach_wps = mission.get("approach", [])
    escort_wps = mission.get("escort", [])
    return_wps = mission.get("return", [])

    total_wps = len(approach_wps) + len(escort_wps) + len(return_wps)
    wp_offset = 0
    battery = 100.0

    # ── Phase 1: Approach at 50 m/s ──────────────────────────────────────────
    await callback({"type": "phase", "phase": "approach"})

    if approach_wps:
        # Fast approach: 5 evenly-spaced updates over ~2 seconds total
        n_updates = 5
        step = max(1, len(approach_wps) // n_updates)
        delay = 0.4  # 5 * 0.4 = 2 seconds total

        for k in range(0, len(approach_wps), step):
            wp = approach_wps[min(k, len(approach_wps) - 1)]
            idx = wp_offset + k
            battery -= 0.1
            heading = 0
            if k + step < len(approach_wps):
                nxt = approach_wps[min(k + step, len(approach_wps) - 1)]
                heading = _bearing(wp["lat"], wp["lng"], nxt["lat"], nxt["lng"])
            await callback({
                "type": "position",
                "lat": wp["lat"], "lng": wp["lng"],
                "alt": wp.get("alt", 60),
                "phase": "approach",
                "ground_speed": 50.0,
                "heading": round(heading),
                "battery_pct": round(battery, 1),
                "waypoint_index": idx,
                "total_waypoints": total_wps,
            })
            await asyncio.sleep(delay)

        # Final approach position — arrived at user
        last_ap = approach_wps[-1]
        await callback({
            "type": "position",
            "lat": last_ap["lat"], "lng": last_ap["lng"],
            "alt": last_ap.get("alt", 60),
            "phase": "approach",
            "ground_speed": 0.0,
            "heading": 0,
            "battery_pct": round(battery, 1),
            "waypoint_index": wp_offset + len(approach_wps) - 1,
            "total_waypoints": total_wps,
        })

    wp_offset += len(approach_wps)
    await asyncio.sleep(0.5)

    # ── Phase 2: Escort — simulate user walking along route ──────────────────
    await callback({"type": "phase", "phase": "escort"})

    if escort_wps:
        WALK_SPEED = 1.4  # displayed speed (real walking)
        DEMO_DELAY = 0.8  # fixed delay between waypoints for demo smoothness

        for i, wp in enumerate(escort_wps):
            idx = wp_offset + i
            battery -= 0.05

            heading = 0
            if i + 1 < len(escort_wps):
                nxt = escort_wps[i + 1]
                heading = _bearing(wp["lat"], wp["lng"], nxt["lat"], nxt["lng"])

            await callback({
                "type": "position",
                "lat": wp["lat"], "lng": wp["lng"],
                "alt": wp.get("alt", 25),
                "phase": "escort",
                "ground_speed": round(WALK_SPEED, 1),
                "heading": round(heading),
                "battery_pct": round(max(10, battery), 1),
                "waypoint_index": idx,
                "total_waypoints": total_wps,
            })

            await callback({
                "type": "user_position",
                "lat": wp["lat"], "lng": wp["lng"],
                "source": "demo",
            })

            if i + 1 < len(escort_wps):
                await asyncio.sleep(DEMO_DELAY)

    wp_offset += len(escort_wps)

    # ── Phase 3: Return — instant snap to hub ────────────────────────────────
    await callback({"type": "phase", "phase": "return"})

    if return_wps:
        hub = return_wps[-1]
        await callback({
            "type": "position",
            "lat": hub["lat"], "lng": hub["lng"],
            "alt": hub.get("alt", 60),
            "phase": "return",
            "ground_speed": 0.0,
            "heading": 0,
            "battery_pct": round(max(10, battery), 1),
            "waypoint_index": total_wps - 1,
            "total_waypoints": total_wps,
        })

    await callback({"type": "complete"})


if __name__ == "__main__":
    mission_file = Path(__file__).parent / "output" / "mission.json"
    if not mission_file.exists():
        print("Run: python waypoint_generator.py first", file=sys.stderr)
        sys.exit(1)

    mission = load_mission(mission_file)
    print(f"approach={len(mission.get('approach',[]))} "
          f"escort={len(mission.get('escort',[]))} "
          f"return={len(mission.get('return',[]))}")

    async def printer(event):
        print(json.dumps(event), flush=True)

    asyncio.run(simulate_mission(mission, printer))
