"""
Louise — MAVLink connector for ArduPilot (SITL and real hardware).

Flies waypoints using GUIDED mode with SET_POSITION_TARGET_GLOBAL_INT,
which is the official ArduCopter GUIDED mode position control method.
Works identically with SITL simulation and real ArduPilot flight controllers.

Connection examples:
  SITL:     tcp:127.0.0.1:5760
  WiFi FC:  tcp:192.168.1.10:5760
  USB:      serial:/dev/ttyUSB0:57600
  UDP:      udp:0.0.0.0:14550

Flow:
  1. Connect to ArduPilot via MAVLink (SITL or real FC)
  2. Arm in GUIDED mode, take off
  3. Fly to each waypoint using SET_POSITION_TARGET_GLOBAL_INT
  4. Stream position telemetry to stdout as JSON lines
  5. Accept live Flystral velocity commands via stdin for obstacle avoidance
  6. RTL when mission complete
"""

from __future__ import annotations

import argparse
import json
import math
import select
import sys
import time
from pathlib import Path

try:
    from pymavlink import mavutil
except ImportError:
    print("pip install pymavlink", file=sys.stderr)
    sys.exit(1)

try:
    from config import (
        APPROACH_RETURN_SPEED,
        ARMING_CHECK as _arming_check,
        ESCORT_SPEED,
        FOLLOW_DISTANCE_M,
        HUB_TO_USER_ALT,
        SIMULATE_BATTERY,
        SIMULATED_BATTERY_START_PCT,
        TAKEOFF_ALT,
        TRACK_ALT,
    )
except ImportError:
    _arming_check = 0
    APPROACH_RETURN_SPEED = 15
    ESCORT_SPEED = 5
    FOLLOW_DISTANCE_M = 15
    HUB_TO_USER_ALT = 60
    TAKEOFF_ALT = 10
    TRACK_ALT = 25
    SIMULATE_BATTERY = True
    SIMULATED_BATTERY_START_PCT = 100

_mission_start_time: float | None = None  # set at mission start for simulated battery


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def connect(connection_string: str) -> mavutil.mavlink_connection:
    log(f"Connecting to {connection_string}...")
    mav = mavutil.mavlink_connection(connection_string)
    log("Waiting for heartbeat...")
    mav.wait_heartbeat(timeout=30)
    log(f"Heartbeat: system {mav.target_system}")

    mav.mav.request_data_stream_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1,
    )

    log("Waiting for GPS fix...")
    for _ in range(10):
        pos = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=2)
        if pos and abs(pos.lat / 1e7) > 1:
            log(f"Position: {pos.lat / 1e7:.6f}, {pos.lon / 1e7:.6f}")
            break
        time.sleep(0.5)
    else:
        log("WARNING: No GPS fix")

    return mav


def _set_param(mav, name: str, value: float):
    mav.mav.param_set_send(
        mav.target_system,
        mav.target_component,
        name.encode().ljust(16, b'\x00')[:16],
        float(value),
        mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
    )
    time.sleep(0.05)


def set_wpnav_speed(mav, speed_m_s: float):
    """Set ArduPilot speed parameters for GUIDED mode flight."""
    speed_cms = int(speed_m_s * 100)
    accel = min(500, max(250, int(speed_m_s * 10)))
    _set_param(mav, "WPNAV_SPEED", speed_cms)
    _set_param(mav, "WPNAV_ACCEL", accel)
    _set_param(mav, "WPNAV_SPEED_UP", min(speed_cms, 500))
    _set_param(mav, "WPNAV_SPEED_DN", min(speed_cms, 300))
    _set_param(mav, "PSC_VELXY_MAX", speed_cms)
    _set_param(mav, "LOIT_SPEED", speed_cms)
    log(f"WPNAV_SPEED={speed_m_s}m/s PSC_VELXY_MAX={speed_cms}cm/s ACCEL={accel}cm/s²")


def set_mode(mav, mode_name: str):
    mode_id = mav.mode_mapping().get(mode_name)
    if mode_id is None:
        log(f"Unknown mode: {mode_name}")
        return
    mav.set_mode(mode_id)
    time.sleep(0.3)
    log(f"Mode → {mode_name}")


def fly_to(mav, lat: float, lng: float, alt: float):
    """Send GUIDED position target using SET_POSITION_TARGET_GLOBAL_INT."""
    # type_mask: use position only (bits 0-2 = 0), ignore vel/acc/yaw
    type_mask = 0b0000111111111000  # 0x0FF8
    mav.mav.set_position_target_global_int_send(
        0,  # time_boot_ms (ignored)
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        type_mask,
        int(lat * 1e7),
        int(lng * 1e7),
        alt,
        0, 0, 0,  # vx, vy, vz (ignored)
        0, 0, 0,  # afx, afy, afz (ignored)
        0, 0,  # yaw, yaw_rate (ignored)
    )


def send_velocity(mav, vx: float, vy: float, vz: float, yaw_rate: float = 0.0):
    """
    Send velocity command to ArduPilot in NED frame.
    vx: forward (north) m/s, vy: right (east) m/s, vz: down m/s
    yaw_rate: rad/s
    Used by Flystral for real-time obstacle avoidance adjustments.
    """
    # type_mask: use velocity only (bits 3-5 = 0), ignore position/accel, use yaw_rate
    type_mask = 0b0000010111000111  # pos ignored, vel used, accel ignored, yaw_rate used
    mav.mav.set_position_target_local_ned_send(
        0,  # time_boot_ms
        mav.target_system,
        mav.target_component,
        mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
        type_mask,
        0, 0, 0,  # x, y, z (ignored)
        vx, vy, vz,
        0, 0, 0,  # afx, afy, afz (ignored)
        0, yaw_rate,
    )


def drain_and_get(mav, msg_type: str):
    """Get the LATEST message of a type, draining any buffered ones first."""
    last = None
    while True:
        msg = mav.recv_match(type=msg_type, blocking=False)
        if msg is None:
            break
        last = msg
    if last is None:
        last = mav.recv_match(type=msg_type, blocking=True, timeout=0.5)
    return last


def get_position(mav) -> tuple[float, float, float] | None:
    last = drain_and_get(mav, "GLOBAL_POSITION_INT")
    if last:
        return last.lat / 1e7, last.lon / 1e7, last.relative_alt / 1000.0
    return None


def get_rich_telemetry(mav) -> dict | None:
    """Get full telemetry from multiple MAVLink messages."""
    pos = drain_and_get(mav, "GLOBAL_POSITION_INT")
    if not pos:
        return None

    result = {
        "lat": pos.lat / 1e7,
        "lng": pos.lon / 1e7,
        "alt": round(pos.relative_alt / 1000.0, 1),
        "heading": round(pos.hdg / 100.0, 1) if pos.hdg != 65535 else 0,
        "vx": round(pos.vx / 100.0, 1),
        "vy": round(pos.vy / 100.0, 1),
        "vz": round(pos.vz / 100.0, 1),
        "ground_speed": round(math.sqrt((pos.vx/100.0)**2 + (pos.vy/100.0)**2), 1),
        "climb_rate": round(-pos.vz / 100.0, 1),
    }

    # Battery (real or simulated)
    if SIMULATE_BATTERY and _mission_start_time is not None:
        elapsed_min = (time.time() - _mission_start_time) / 60.0
        drain_pct_per_min = 1.5  # realistic for a ~25 min max flight
        result["battery_pct"] = max(0, int(SIMULATED_BATTERY_START_PCT - elapsed_min * drain_pct_per_min))
        result["voltage"] = round(11.1 + (result["battery_pct"] / 100.0) * 2.7, 1)
    else:
        bat = drain_and_get(mav, "SYS_STATUS")
        if bat and bat.battery_remaining >= 0:
            result["battery_pct"] = bat.battery_remaining
            result["voltage"] = round(bat.voltage_battery / 1000.0, 1)
        else:
            result["battery_pct"] = -1
            result["voltage"] = 0

    # Attitude (roll/pitch/yaw)
    att = drain_and_get(mav, "ATTITUDE")
    if att:
        result["roll"] = round(math.degrees(att.roll), 1)
        result["pitch"] = round(math.degrees(att.pitch), 1)
        result["yaw"] = round(math.degrees(att.yaw), 1)

    # GPS info
    gps = drain_and_get(mav, "GPS_RAW_INT")
    if gps:
        result["satellites"] = gps.satellites_visible
        result["gps_fix"] = gps.fix_type

    return result


def arm_and_takeoff(mav, altitude: float):
    mav.mav.param_set_send(
        mav.target_system, mav.target_component,
        b'ARMING_CHECK', _arming_check, mavutil.mavlink.MAV_PARAM_TYPE_INT32,
    )
    time.sleep(0.3)

    pos = get_position(mav)
    hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
    already_armed = hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    already_airborne = pos and pos[2] > 3.0

    if already_armed and already_airborne:
        log(f"Already armed and airborne at {pos[2]:.1f}m")
        set_mode(mav, "GUIDED")
        time.sleep(0.3)
        log("Ready for navigation")
        return

    set_mode(mav, "GUIDED")
    time.sleep(0.5)

    for attempt in range(5):
        log(f"Arming ({attempt + 1}/5)...")
        mav.arducopter_arm()
        ack = mav.recv_match(type='COMMAND_ACK', blocking=True, timeout=2)
        if ack:
            log(f"  ACK: cmd={ack.command} result={ack.result}")
        for _ in range(10):
            hb = mav.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
            if hb and (hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                log("Armed")
                break
        else:
            time.sleep(1)
            continue
        break
    else:
        log("WARNING: arm not confirmed")

    log(f"Takeoff → {altitude}m")
    mav.mav.command_long_send(
        mav.target_system, mav.target_component,
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        0, 0, 0, 0, 0, 0, 0, altitude,
    )

    ack = mav.recv_match(type='COMMAND_ACK', blocking=True, timeout=3)
    if ack:
        log(f"  Takeoff ACK: cmd={ack.command} result={ack.result}")

    for _ in range(60):
        msg = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=1)
        if msg:
            alt_now = msg.relative_alt / 1000.0
            if alt_now >= altitude * 0.85:
                log(f"Reached {alt_now:.1f}m")
                break
        time.sleep(0.3)
    else:
        log("WARNING: Takeoff altitude not confirmed")

    time.sleep(1)

    pos = get_position(mav)
    if pos:
        log(f"Position hold at {pos[0]:.6f}, {pos[1]:.6f}, {pos[2]:.1f}m")
        fly_to(mav, pos[0], pos[1], pos[2])
        time.sleep(0.5)

    log("Ready for navigation")


def position_behind_user(user_lat: float, user_lng: float, bearing_rad: float, distance_m: float) -> tuple[float, float]:
    """Target position 'distance_m' behind user along bearing (user's direction of travel)."""
    # Behind = opposite to bearing: add (distance_m * cos(bearing), distance_m * sin(bearing)) in north/east metres, negated
    north_m = -distance_m * math.cos(bearing_rad)
    east_m = -distance_m * math.sin(bearing_rad)
    m_per_deg_lat = 111320
    m_per_deg_lng = 111320 * math.cos(math.radians(user_lat))
    target_lat = user_lat + north_m / m_per_deg_lat
    target_lng = user_lng + east_m / m_per_deg_lng
    return target_lat, target_lng


def live_follow_loop(mav, follow_distance_m: float, track_alt: float, total_waypoints: int):
    """
    Read user_position from stdin, fly to position behind user at track_alt.
    Exit when stdin receives {"type": "phase", "phase": "return"}.
    """
    log("Entering live follow — waiting for user position on stdin")
    last_user_lat, last_user_lng = None, None
    bearing_rad = 0.0  # north
    offset_dlat, offset_dlng, offset_dalt = 0.0, 0.0, 0.0
    pending_velocity = None  # (vx, vy, vz, yaw_rate) from Flystral

    while True:
        # Non-blocking read stdin (Unix)
        if select.select([sys.stdin], [], [], 0.2)[0]:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "phase" and msg.get("phase") == "return":
                    log("Received phase return — exiting live follow")
                    return
                if msg.get("type") == "user_position":
                    lat, lng = float(msg["lat"]), float(msg["lng"])
                    if last_user_lat is not None and last_user_lng is not None:
                        dlat = math.radians(lat - last_user_lat)
                        dlng = math.radians(lng - last_user_lng) * math.cos(math.radians(lat))
                        if dlat != 0 or dlng != 0:
                            bearing_rad = math.atan2(dlng, dlat)
                    last_user_lat, last_user_lng = lat, lng
                if msg.get("type") == "hold_position":
                    log("Hold position — operator review pending")
                    pending_velocity = None
                    continue
                if msg.get("type") == "flystral_offset":
                    offset_dlat = float(msg.get("dlat", 0))
                    offset_dlng = float(msg.get("dlng", 0))
                    offset_dalt = float(msg.get("dalt", 0))
                    if "dyaw" in msg:
                        offset_dyaw = float(msg.get("dyaw", 0))
                        bearing_rad = (bearing_rad or 0) + math.radians(offset_dyaw)
                    vel = msg.get("velocity")
                    if vel and any(vel.get(k, 0) != 0 for k in ("vx", "vy", "vz", "yaw_rate")):
                        pending_velocity = (
                            float(vel.get("vx", 0)),
                            float(vel.get("vy", 0)),
                            float(vel.get("vz", 0)),
                            float(vel.get("yaw_rate", 0)),
                        )
                        log(f"Flystral velocity: vx={pending_velocity[0]:.1f} vy={pending_velocity[1]:.1f} vz={pending_velocity[2]:.1f}")
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

        if last_user_lat is None or last_user_lng is None:
            telem = get_rich_telemetry(mav)
            if telem:
                event = {
                    "type": "position",
                    "lat": round(telem["lat"], 7),
                    "lng": round(telem["lng"], 7),
                    "alt": telem["alt"],
                    "heading": telem.get("heading", 0),
                    "ground_speed": telem.get("ground_speed", 0),
                    "climb_rate": telem.get("climb_rate", 0),
                    "battery_pct": telem.get("battery_pct", -1),
                    "voltage": telem.get("voltage", 0),
                    "roll": telem.get("roll", 0),
                    "pitch": telem.get("pitch", 0),
                    "yaw": telem.get("yaw", 0),
                    "satellites": telem.get("satellites", 0),
                    "phase": "escort",
                    "waypoint_index": 0,
                    "total_waypoints": total_waypoints,
                }
                print(json.dumps(event), flush=True)
            time.sleep(0.5)
            continue

        if pending_velocity:
            vx, vy, vz, yr = pending_velocity
            send_velocity(mav, vx, vy, vz, yr)
            pending_velocity = None
        else:
            target_lat, target_lng = position_behind_user(last_user_lat, last_user_lng, bearing_rad, follow_distance_m)
            target_lat += offset_dlat
            target_lng += offset_dlng
            alt_m = track_alt + offset_dalt
            fly_to(mav, target_lat, target_lng, max(5.0, alt_m))

        telem = get_rich_telemetry(mav)
        if telem:
            event = {
                "type": "position",
                "lat": round(telem["lat"], 7),
                "lng": round(telem["lng"], 7),
                "alt": telem["alt"],
                "heading": telem.get("heading", 0),
                "ground_speed": telem.get("ground_speed", 0),
                "climb_rate": telem.get("climb_rate", 0),
                "battery_pct": telem.get("battery_pct", -1),
                "voltage": telem.get("voltage", 0),
                "roll": telem.get("roll", 0),
                "pitch": telem.get("pitch", 0),
                "yaw": telem.get("yaw", 0),
                "satellites": telem.get("satellites", 0),
                "dist_to_wp": round(haversine(telem["lat"], telem["lng"], target_lat, target_lng), 1),
                "phase": "escort",
                "waypoint_index": 0,
                "total_waypoints": total_waypoints,
            }
            print(json.dumps(event), flush=True)

        time.sleep(0.4)


def fly_waypoints(mav, waypoints: list[dict], wp_accept_radius: float = 8.0) -> None:
    """Fly a list of waypoints in GUIDED mode. Streams telemetry to stdout."""
    total = len(waypoints)
    for i, wp in enumerate(waypoints):
        target_lat = wp["lat"]
        target_lng = wp["lng"]
        target_alt = wp["alt"]
        phase = wp.get("phase", "unknown")

        pos = get_position(mav)
        if pos:
            lat, lng, _ = pos
            if haversine(lat, lng, target_lat, target_lng) < wp_accept_radius:
                continue

        fly_to(mav, target_lat, target_lng, target_alt)
        time.sleep(0.3)

        if i % 10 == 0 or i == total - 1:
            log(f"WP {i + 1}/{total} [{phase}] → ({target_lat:.5f}, {target_lng:.5f}, {target_alt}m)")

        stuck_count = 0
        last_dist = None

        while True:
            telem = get_rich_telemetry(mav)
            if telem is None:
                continue

            lat, lng, alt = telem["lat"], telem["lng"], telem["alt"]
            dist = haversine(lat, lng, target_lat, target_lng)

            event = {
                "type": "position",
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "alt": alt,
                "heading": telem.get("heading", 0),
                "ground_speed": telem.get("ground_speed", 0),
                "climb_rate": telem.get("climb_rate", 0),
                "battery_pct": telem.get("battery_pct", -1),
                "voltage": telem.get("voltage", 0),
                "roll": telem.get("roll", 0),
                "pitch": telem.get("pitch", 0),
                "yaw": telem.get("yaw", 0),
                "satellites": telem.get("satellites", 0),
                "dist_to_wp": round(dist, 1),
                "phase": phase,
                "waypoint_index": i,
                "total_waypoints": total,
            }
            print(json.dumps(event), flush=True)

            if dist < wp_accept_radius:
                print(json.dumps({"type": "waypoint_reached", "seq": i, "phase": phase}), flush=True)
                break

            if stuck_count % 10 == 9:
                fly_to(mav, target_lat, target_lng, target_alt)

            if last_dist is not None and dist >= last_dist - 0.5:
                stuck_count += 1
                if stuck_count > 60:
                    log(f"WP {i + 1}: stuck at {dist:.0f}m, skipping")
                    break
            else:
                stuck_count = 0
            last_dist = dist

            time.sleep(0.5)


def fly_mission(mav, waypoints: list[dict]):
    """Fly approach waypoints, then live follow (stdin), then return waypoints, then RTL."""
    approach = [w for w in waypoints if w.get("phase") == "approach"]
    escort = [w for w in waypoints if w.get("phase") == "escort"]
    return_wps = [w for w in waypoints if w.get("phase") == "return"]
    total = len(waypoints)

    # Thin out approach/return waypoints so the drone can build speed
    # between them instead of slowing for every closely-spaced point
    def thin_waypoints(wps, min_spacing_m=50):
        if len(wps) <= 2:
            return wps
        thinned = [wps[0]]
        for wp in wps[1:-1]:
            prev = thinned[-1]
            if haversine(prev["lat"], prev["lng"], wp["lat"], wp["lng"]) >= min_spacing_m:
                thinned.append(wp)
        thinned.append(wps[-1])
        return thinned

    approach_thinned = thin_waypoints(approach, min_spacing_m=80)
    return_thinned = thin_waypoints(return_wps, min_spacing_m=80)

    log(f"Approach: {len(approach_thinned)} wp (thinned from {len(approach)}), then live follow, then return: {len(return_thinned)} (from {len(return_wps)})")

    # Speed up SITL simulation for approach phase (5x real time)
    _set_param(mav, "SIM_SPEEDUP", 5.0)
    set_wpnav_speed(mav, APPROACH_RETURN_SPEED)
    fly_waypoints(mav, approach_thinned)

    # Return to real-time for escort (walking speed tracking)
    _set_param(mav, "SIM_SPEEDUP", 1.0)
    set_wpnav_speed(mav, ESCORT_SPEED)
    live_follow_loop(mav, FOLLOW_DISTANCE_M, TRACK_ALT, total)

    # Speed up again for return phase
    _set_param(mav, "SIM_SPEEDUP", 5.0)
    set_wpnav_speed(mav, APPROACH_RETURN_SPEED)
    fly_waypoints(mav, return_thinned)

    log("Return complete — RTL")
    set_mode(mav, "RTL")

    for _ in range(120):
        pos = get_position(mav)
        if pos:
            lat, lng, alt = pos
            event = {
                "type": "position",
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "alt": round(alt, 1),
                "phase": "return",
                "waypoint_index": total - 1,
                "total_waypoints": total,
            }
            print(json.dumps(event), flush=True)
            if alt < 1.0:
                break
        time.sleep(1)

    print(json.dumps({"type": "complete"}), flush=True)
    log("Done")


def load_waypoints_from_json(json_path: Path) -> list[dict]:
    with open(json_path) as f:
        data = json.load(f)

    waypoints = []
    for phase in ("approach", "escort", "return"):
        for wp in data.get(phase, []):
            waypoints.append({
                "lat": wp["lat"],
                "lng": wp["lng"],
                "alt": wp["alt"],
                "phase": phase,
            })
    return waypoints


def main():
    global _mission_start_time
    parser = argparse.ArgumentParser(description="Louise MAVLink GUIDED-mode flight")
    parser.add_argument("--connection", default="tcp:127.0.0.1:5760")
    parser.add_argument("--mission-json", default="autopilot_adapter/output/mission.json")
    parser.add_argument("--altitude", type=float, default=None, help="Takeoff/approach alt (default from config)")
    args = parser.parse_args()

    takeoff_alt = args.altitude if args.altitude is not None else TAKEOFF_ALT

    json_path = Path(args.mission_json)
    if not json_path.exists():
        log(f"Mission JSON not found: {json_path}")
        sys.exit(1)

    waypoints = load_waypoints_from_json(json_path)
    if not waypoints:
        log("No waypoints in mission JSON")
        sys.exit(1)

    log(f"Loaded {len(waypoints)} waypoints from {json_path}")

    mav = connect(args.connection)
    _mission_start_time = time.time()
    set_wpnav_speed(mav, APPROACH_RETURN_SPEED)
    arm_and_takeoff(mav, takeoff_alt)
    fly_mission(mav, waypoints)


if __name__ == "__main__":
    main()
