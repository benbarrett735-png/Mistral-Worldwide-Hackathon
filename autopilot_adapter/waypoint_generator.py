"""
Waypoint generator for Louise / ArduPilot SITL.

Produces:
  1. mission.waypoints  — QGC WPL 110 format (loadable by ArduPilot SITL / MAVProxy / QGC)
  2. mission.json       — structured JSON for the web UI
  3. mission.plan       — QGC .plan JSON format

Three flight phases:
  Phase 1 (approach):  Hub → User location (fly at approach altitude)
  Phase 2 (escort):    Follow user's walking route (lower altitude, camera tracking)
  Phase 3 (return):    User destination → Hub (climb back to transit altitude)

Walking route coordinates come from OSRM (real street-following polyline).
The escort phase samples waypoints along the walking route to create a
flyable path that actually follows the streets.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Sequence

# Use config when available (project root); else defaults for standalone use
try:
    from config import (
        HUB_TO_USER_ALT as APPROACH_ALT,
        TRACK_ALT as ESCORT_ALT,
        HOME_ALT as RETURN_ALT,
        TAKEOFF_ALT,
        CRUISE_SPEED,
    )
except ImportError:
    APPROACH_ALT = 60
    ESCORT_ALT = 25
    RETURN_ALT = 60
    TAKEOFF_ALT = 10
    CRUISE_SPEED = 15

# MAVLink command IDs
MAV_CMD_NAV_TAKEOFF = 22
MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_RETURN_TO_LAUNCH = 20
MAV_CMD_NAV_LAND = 21
MAV_CMD_DO_CHANGE_SPEED = 178

MAV_FRAME_GLOBAL_RELATIVE_ALT = 3


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in metres between two lat/lng points."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def sample_route(coords: list[tuple[float, float]], max_spacing_m: float = 30) -> list[tuple[float, float]]:
    """
    Resample a route so waypoints are at most max_spacing_m apart.
    Input: list of (lat, lng). Keeps all original points but inserts
    interpolated ones where gaps are too large.
    For ArduPilot copter, ~30m spacing gives smooth path following.
    """
    if len(coords) < 2:
        return list(coords)

    result = [coords[0]]
    for i in range(1, len(coords)):
        prev = result[-1]
        curr = coords[i]
        dist = haversine(prev[0], prev[1], curr[0], curr[1])

        if dist > max_spacing_m:
            n_segments = max(2, int(math.ceil(dist / max_spacing_m)))
            for j in range(1, n_segments):
                t = j / n_segments
                lat = prev[0] + t * (curr[0] - prev[0])
                lng = prev[1] + t * (curr[1] - prev[1])
                result.append((lat, lng))

        result.append(curr)

    return result


def generate_approach(hub: tuple[float, float], user: tuple[float, float]) -> list[dict]:
    """Phase 1: Hub → User. Straight line at approach altitude with sampled points."""
    points = sample_route([hub, user], max_spacing_m=50)
    return [
        {"lat": lat, "lng": lng, "alt": APPROACH_ALT, "phase": "approach",
         "command": MAV_CMD_NAV_WAYPOINT}
        for lat, lng in points
    ]


def generate_escort(walking_route: list[tuple[float, float]]) -> list[dict]:
    """Phase 2: Follow user along their walking route at escort altitude."""
    sampled = sample_route(walking_route, max_spacing_m=50)
    return [
        {"lat": lat, "lng": lng, "alt": ESCORT_ALT, "phase": "escort",
         "command": MAV_CMD_NAV_WAYPOINT}
        for lat, lng in sampled
    ]


def generate_return(destination: tuple[float, float], hub: tuple[float, float]) -> list[dict]:
    """Phase 3: User destination → Hub. Straight line at return altitude."""
    points = sample_route([destination, hub], max_spacing_m=50)
    return [
        {"lat": lat, "lng": lng, "alt": RETURN_ALT, "phase": "return",
         "command": MAV_CMD_NAV_WAYPOINT}
        for lat, lng in points
    ]


def generate_from_osrm(
    hub: tuple[float, float],
    osrm_coords: list[list[float]],
) -> dict:
    """
    Build a complete mission from OSRM route coordinates.
    osrm_coords: [[lng, lat], ...] as returned by OSRM.
    """
    route_latlng = [(c[1], c[0]) for c in osrm_coords]
    user = route_latlng[0]
    destination = route_latlng[-1]

    approach = generate_approach(hub, user)
    escort = generate_escort(route_latlng)
    ret = generate_return(destination, hub)

    return _build_mission(hub, approach, escort, ret, user, destination)


def generate_all(
    hub: tuple[float, float],
    user: tuple[float, float],
    walking_route: Sequence[tuple[float, float]],
    destination: tuple[float, float],
) -> dict:
    """Build mission from explicit coordinates."""
    approach = generate_approach(hub, user)
    escort = generate_escort(list(walking_route))
    ret = generate_return(destination, hub)

    return _build_mission(hub, approach, escort, ret, user, destination)


# Keep old name as alias for backward compatibility
generate_from_ors_route = generate_from_osrm


def _build_mission(hub, approach, escort, ret, user, destination) -> dict:
    all_wps = approach + escort + ret

    total_dist = 0
    for i in range(1, len(all_wps)):
        total_dist += haversine(all_wps[i-1]["lat"], all_wps[i-1]["lng"],
                                all_wps[i]["lat"], all_wps[i]["lng"])

    return {
        "approach": approach,
        "escort": escort,
        "return": ret,
        "user": {"lat": user[0], "lng": user[1]},
        "destination": {"lat": destination[0], "lng": destination[1]},
        "hub": {"lat": hub[0], "lng": hub[1]},
        "stats": {
            "total_waypoints": len(all_wps),
            "approach_wp": len(approach),
            "escort_wp": len(escort),
            "return_wp": len(ret),
            "total_distance_m": round(total_dist),
            "estimated_flight_time_s": round(total_dist / CRUISE_SPEED),
        },
        "ardupilot_wpl": to_ardupilot_wpl(hub, all_wps),
        "qgc_plan": to_qgc_plan(hub, all_wps),
    }


def to_ardupilot_wpl(hub: tuple[float, float], waypoints: list[dict]) -> str:
    """
    Generate ArduPilot waypoint file (QGC WPL 110 format).
    This is the format loaded by MAVProxy `wp load` and QGroundControl.

    Format per line:
    <seq> <current> <frame> <command> <p1> <p2> <p3> <p4> <lat> <lng> <alt> <autocontinue>
    """
    lines = ["QGC WPL 110"]

    # Home position (seq 0)
    lines.append(f"0\t1\t0\t{MAV_CMD_NAV_WAYPOINT}\t0\t0\t0\t0\t{hub[0]:.8f}\t{hub[1]:.8f}\t0.000000\t1")

    seq = 1

    # Takeoff
    lines.append(f"{seq}\t0\t{MAV_FRAME_GLOBAL_RELATIVE_ALT}\t{MAV_CMD_NAV_TAKEOFF}\t0\t0\t0\t0\t{hub[0]:.8f}\t{hub[1]:.8f}\t{TAKEOFF_ALT:.6f}\t1")
    seq += 1

    # Set speed
    lines.append(f"{seq}\t0\t{MAV_FRAME_GLOBAL_RELATIVE_ALT}\t{MAV_CMD_DO_CHANGE_SPEED}\t0\t{CRUISE_SPEED}\t0\t0\t0.00000000\t0.00000000\t0.000000\t1")
    seq += 1

    # All mission waypoints
    for wp in waypoints:
        lines.append(f"{seq}\t0\t{MAV_FRAME_GLOBAL_RELATIVE_ALT}\t{MAV_CMD_NAV_WAYPOINT}\t0\t0\t0\t0\t{wp['lat']:.8f}\t{wp['lng']:.8f}\t{wp['alt']:.6f}\t1")
        seq += 1

    # Return to launch
    lines.append(f"{seq}\t0\t{MAV_FRAME_GLOBAL_RELATIVE_ALT}\t{MAV_CMD_NAV_RETURN_TO_LAUNCH}\t0\t0\t0\t0\t0.00000000\t0.00000000\t0.000000\t1")

    return "\n".join(lines)


def to_qgc_plan(hub: tuple[float, float], waypoints: list[dict]) -> dict:
    """QGroundControl .plan JSON format."""
    items = []
    seq = 1

    items.append({
        "autoContinue": True,
        "command": MAV_CMD_NAV_TAKEOFF,
        "coordinate": [hub[0], hub[1], TAKEOFF_ALT],
        "doJumpId": seq,
        "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
        "params": [0, 0, 0, None],
        "type": "SimpleItem",
    })
    seq += 1

    for wp in waypoints:
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_WAYPOINT,
            "coordinate": [wp["lat"], wp["lng"], wp["alt"]],
            "doJumpId": seq,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0, 0, 0, None],
            "type": "SimpleItem",
        })
        seq += 1

    items.append({
        "autoContinue": True,
        "command": MAV_CMD_NAV_RETURN_TO_LAUNCH,
        "coordinate": [0, 0, 0],
        "doJumpId": seq,
        "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
        "params": [0, 0, 0, 0],
        "type": "SimpleItem",
    })

    return {
        "fileType": "Plan",
        "geoFence": {"circles": [], "polygons": [], "version": 2},
        "groundStation": "Louise",
        "mission": {
            "cruiseSpeed": CRUISE_SPEED,
            "firmwareType": 3,
            "globalPlanAltitudeMode": 1,
            "hoverSpeed": CRUISE_SPEED,
            "items": items,
            "plannedHomePosition": [hub[0], hub[1], 0],
            "vehicleType": 2,
            "version": 2,
        },
        "rallyPoints": {"points": [], "version": 2},
        "version": 1,
    }


def save_mission(mission: dict, out_dir: Path) -> dict:
    """Save all mission file formats to disk."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # ArduPilot WPL (the one SITL actually loads)
    wpl_path = out_dir / "mission.waypoints"
    wpl_path.write_text(mission["ardupilot_wpl"])

    # JSON for web UI
    json_path = out_dir / "mission.json"
    with open(json_path, "w") as f:
        json.dump({
            "approach": mission["approach"],
            "escort": mission["escort"],
            "return": mission["return"],
            "stats": mission["stats"],
            "hub": mission["hub"],
            "user": mission["user"],
            "destination": mission["destination"],
        }, f, indent=2)

    # QGC plan
    plan_path = out_dir / "mission.plan"
    with open(plan_path, "w") as f:
        json.dump(mission["qgc_plan"], f, indent=2)

    return {
        "waypoints_file": str(wpl_path),
        "json_file": str(json_path),
        "plan_file": str(plan_path),
    }


if __name__ == "__main__":
    import httpx

    HUB = (48.8606, 2.3376)  # Louvre drone centre
    START = (48.8620, 2.3310)  # Louvre area
    END = (48.8530, 2.3499)    # Saint-Germain

    print("Fetching real walking route from OSRM...")
    resp = httpx.get(
        f"http://router.project-osrm.org/route/v1/foot/{START[1]},{START[0]};{END[1]},{END[0]}?overview=full&geometries=geojson"
    )
    route_data = resp.json()["routes"][0]
    osrm_coords = route_data["geometry"]["coordinates"]
    print(f"  Route: {route_data['distance']:.0f}m, {len(osrm_coords)} points from OSRM")

    mission = generate_from_osrm(HUB, osrm_coords)
    print(f"  Total: {mission['stats']['total_waypoints']} waypoints, {mission['stats']['total_distance_m']}m")
    print(f"  Approach: {mission['stats']['approach_wp']} wp")
    print(f"  Escort: {mission['stats']['escort_wp']} wp")
    print(f"  Return: {mission['stats']['return_wp']} wp")

    out = Path(__file__).parent / "output"
    files = save_mission(mission, out)
    print(f"\nFiles written:")
    for k, v in files.items():
        print(f"  {k}: {v}")

    print(f"\nArduPilot WPL (first 10 lines):")
    for line in mission["ardupilot_wpl"].split("\n")[:10]:
        print(f"  {line}")
