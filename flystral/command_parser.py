"""
Flystral command parser.
Converts Flystral output into waypoint/velocity adjustments for the drone connector.

Supports two output modes:
  1. Velocity vectors (vx, vy, vz, yaw_rate) — from fine-tuned model trained on AirSim data.
     These map directly to drone body-frame velocities and are the primary mode.
  2. Discrete commands (FOLLOW, AVOID_LEFT, etc.) — legacy/fallback mode from prompt-based output.
"""

from __future__ import annotations

import math

VALID_COMMANDS = {"FOLLOW", "AVOID_LEFT", "AVOID_RIGHT", "CLIMB", "HOVER", "REPLAN", "DESCEND"}

# AirSim training data normalization constants
VELOCITY_MEANS = [2.43, 0.0, 0.025, -1.17]
VELOCITY_STDS = [0.87, 1e-6, 0.32, 20.56]

# Safety clamps for velocity output
MAX_HORIZONTAL_MS = 5.0
MAX_VERTICAL_MS = 3.0
MAX_YAW_RATE_DEG = 45.0


def velocity_to_offset(vx: float, vy: float, vz: float, yaw_rate: float,
                       heading_rad: float = 0.0, dt: float = 1.0) -> dict:
    """
    Convert body-frame velocity vector to GPS offset (dlat, dlng, dalt).

    vx: forward speed (m/s, body frame)
    vy: lateral speed (m/s, positive = right)
    vz: vertical speed (m/s, positive = up)
    yaw_rate: degrees/s
    heading_rad: current drone heading in radians (0 = north)
    dt: time step in seconds (how far ahead to project)
    """
    vx = max(-MAX_HORIZONTAL_MS, min(MAX_HORIZONTAL_MS, vx))
    vy = max(-MAX_HORIZONTAL_MS, min(MAX_HORIZONTAL_MS, vy))
    vz = max(-MAX_VERTICAL_MS, min(MAX_VERTICAL_MS, vz))
    yaw_rate = max(-MAX_YAW_RATE_DEG, min(MAX_YAW_RATE_DEG, yaw_rate))

    north_ms = vx * math.cos(heading_rad) - vy * math.sin(heading_rad)
    east_ms = vx * math.sin(heading_rad) + vy * math.cos(heading_rad)

    m_per_deg_lat = 111_320
    m_per_deg_lng = 111_320 * math.cos(math.radians(48.86))

    dlat = (north_ms * dt) / m_per_deg_lat
    dlng = (east_ms * dt) / m_per_deg_lng
    dalt = vz * dt

    return {
        "dlat": dlat,
        "dlng": dlng,
        "dalt": dalt,
        "dyaw": yaw_rate * dt,
        "vx": round(vx, 2),
        "vy": round(vy, 2),
        "vz": round(vz, 2),
        "yaw_rate": round(yaw_rate, 1),
    }


def denormalize_velocity(normed_vx: float, normed_vy: float,
                         normed_vz: float, normed_yaw: float) -> tuple[float, float, float, float]:
    """Denormalize model output using AirSim training data statistics."""
    vx = normed_vx * VELOCITY_STDS[0] + VELOCITY_MEANS[0]
    vy = normed_vy * VELOCITY_STDS[1] + VELOCITY_MEANS[1]
    vz = normed_vz * VELOCITY_STDS[2] + VELOCITY_MEANS[2]
    yaw = normed_yaw * VELOCITY_STDS[3] + VELOCITY_MEANS[3]
    return vx, vy, vz, yaw


def parse_velocity_output(result: dict, heading_rad: float = 0.0) -> dict:
    """
    Parse Flystral output that contains velocity vectors.
    Handles both raw and normalized outputs.
    """
    if "vx" in result:
        vx = float(result.get("vx", 0))
        vy = float(result.get("vy", 0))
        vz = float(result.get("vz", 0))
        yaw = float(result.get("yaw_rate", 0))

        if result.get("normalized", False):
            vx, vy, vz, yaw = denormalize_velocity(vx, vy, vz, yaw)

        return velocity_to_offset(vx, vy, vz, yaw, heading_rad)

    return {"dlat": 0, "dlng": 0, "dalt": 0, "dyaw": 0, "vx": 0, "vy": 0, "vz": 0, "yaw_rate": 0}


def parse_to_waypoint_update(command: str, param: str, current_wp: dict) -> dict:
    """
    Legacy: convert discrete command to waypoint adjustment.
    Used when model outputs discrete commands instead of velocity vectors.
    """
    update = dict(current_wp)
    update["flystral_command"] = command
    update["flystral_param"] = param

    try:
        val = float(param)
    except (ValueError, TypeError):
        val = 0.0

    if command == "FOLLOW":
        update["speed"] = val
    elif command == "AVOID_LEFT":
        update["lng"] = current_wp["lng"] - (val / 111_320) * 1.5
    elif command == "AVOID_RIGHT":
        update["lng"] = current_wp["lng"] + (val / 111_320) * 1.5
    elif command == "CLIMB":
        update["alt"] = current_wp["alt"] + val
    elif command == "DESCEND":
        update["alt"] = max(10, current_wp["alt"] - val)
    elif command == "HOVER":
        update["hover_seconds"] = val
    elif command == "REPLAN":
        update["replan"] = True

    return update


def apply_command(event: dict, current_wp: dict) -> dict:
    """Convenience wrapper for legacy discrete command mode."""
    return parse_to_waypoint_update(
        event.get("command", "FOLLOW"),
        event.get("param", "0.5"),
        current_wp,
    )
