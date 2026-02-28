"""
Waypoint generator for Helpstroll/Flystroll.
Generates flight paths for: Hub->User, Track (along route), Home (destination->hub).
Output: JSON (simple + QGC .plan compatible), usable by ArduPilot SITL or mock sim.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

MAV_CMD_NAV_WAYPOINT = 16
MAV_FRAME_GLOBAL_RELATIVE_ALT = 3

HUB_TO_USER_ALT = 50
TRACK_ALT = 25
HOME_ALT = 50


def offset_route(route: Sequence[tuple[float, float]], alt: float) -> list[dict]:
    """Convert a 2D route to 3D waypoints with fixed altitude."""
    return [
        {"lat": lat, "lng": lng, "alt": alt, "command": MAV_CMD_NAV_WAYPOINT}
        for lat, lng in route
    ]


def generate_hub_to_user(hub: tuple[float, float], user: tuple[float, float]) -> list[dict]:
    """Hub -> User: straight line with intermediate points."""
    lat1, lng1 = hub
    lat2, lng2 = user
    waypoints = []
    for i in range(11):
        t = i / 10
        lat = lat1 + t * (lat2 - lat1)
        lng = lng1 + t * (lng2 - lng1)
        alt = HUB_TO_USER_ALT * (1 - t * 0.6)
        waypoints.append({"lat": lat, "lng": lng, "alt": alt, "command": MAV_CMD_NAV_WAYPOINT, "phase": "hub_to_user"})
    return waypoints


def generate_track_route(route: Sequence[tuple[float, float]]) -> list[dict]:
    """Track user along walking route at escort altitude."""
    return [
        {"lat": lat, "lng": lng, "alt": TRACK_ALT, "command": MAV_CMD_NAV_WAYPOINT, "phase": "track"}
        for lat, lng in route
    ]


def generate_home(hub: tuple[float, float], destination: tuple[float, float]) -> list[dict]:
    """Destination -> Hub: fly home climbing to safe altitude."""
    lat1, lng1 = destination
    lat2, lng2 = hub
    waypoints = []
    for i in range(11):
        t = i / 10
        lat = lat1 + t * (lat2 - lat1)
        lng = lng1 + t * (lng2 - lng1)
        alt = TRACK_ALT + t * (HOME_ALT - TRACK_ALT)
        waypoints.append({"lat": lat, "lng": lng, "alt": alt, "command": MAV_CMD_NAV_WAYPOINT, "phase": "home"})
    return waypoints


def generate_from_ors_route(
    hub: tuple[float, float],
    ors_coords: list[list[float]],
) -> dict:
    """
    Accept an ORS route polyline (list of [lng, lat] pairs as returned by ORS)
    and generate all three flight phases.
    ORS returns coordinates as [longitude, latitude] -- we swap to (lat, lng).
    """
    route_latlng = [(c[1], c[0]) for c in ors_coords]
    user = route_latlng[0]
    destination = route_latlng[-1]

    hub_to_user = generate_hub_to_user(hub, user)
    track = generate_track_route(route_latlng)
    home = generate_home(hub, destination)

    return {
        "hub_to_user": hub_to_user,
        "track": track,
        "home": home,
        "user": {"lat": user[0], "lng": user[1]},
        "destination": {"lat": destination[0], "lng": destination[1]},
        "qgc_plan": to_qgc_plan(hub, hub_to_user, track, home),
    }


def generate_all(
    hub: tuple[float, float],
    user: tuple[float, float],
    walking_route: Sequence[tuple[float, float]],
    destination: tuple[float, float],
) -> dict:
    """Generate all three flight phases from explicit coordinates."""
    hub_to_user = generate_hub_to_user(hub, user)
    track = generate_track_route(walking_route)
    home = generate_home(hub, destination)

    return {
        "hub_to_user": hub_to_user,
        "track": track,
        "home": home,
        "user": {"lat": user[0], "lng": user[1]},
        "destination": {"lat": destination[0], "lng": destination[1]},
        "qgc_plan": to_qgc_plan(hub, hub_to_user, track, home),
    }


def to_qgc_plan(
    hub: tuple[float, float],
    hub_to_user: list[dict],
    track: list[dict],
    home: list[dict],
) -> dict:
    """Build QGroundControl .plan compatible JSON."""
    items = []
    seq = 1

    items.append({
        "autoContinue": True,
        "command": 22,
        "coordinate": [hub[0], hub[1], 0],
        "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
        "id": seq,
        "param1": 0, "param2": 0, "param3": 0, "param4": 0,
        "type": "missionItem",
    })
    seq += 1

    for wp in hub_to_user + track + home:
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_WAYPOINT,
            "coordinate": [wp["lat"], wp["lng"], wp["alt"]],
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "id": seq,
            "param1": 0, "param2": 0, "param3": 0, "param4": 0,
            "type": "missionItem",
        })
        seq += 1

    return {
        "MAV_AUTOPILOT": 3,
        "complexItems": [],
        "groundStation": "Helpstroll",
        "items": items,
        "plannedHomePosition": {
            "id": 1,
            "coordinate": [hub[0], hub[1], 0],
            "type": "missionItem",
        },
        "version": "1.0",
    }


if __name__ == "__main__":
    HUB = (48.8809, 2.3553)
    USER = (48.8795, 2.3565)
    DEST = (48.8765, 2.3600)
    WALKING_ROUTE = [
        (48.8795, 2.3565),
        (48.8785, 2.3580),
        (48.8775, 2.3590),
        (48.8765, 2.3600),
    ]

    result = generate_all(HUB, USER, WALKING_ROUTE, DEST)

    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)

    with open(out_dir / "mission.json", "w") as f:
        json.dump({
            "hub_to_user": result["hub_to_user"],
            "track": result["track"],
            "home": result["home"],
        }, f, indent=2)

    with open(out_dir / "mission.plan", "w") as f:
        json.dump(result["qgc_plan"], f, indent=2)

    print(f"Generated {len(result['hub_to_user'])} hub->user, {len(result['track'])} track, {len(result['home'])} home waypoints")
