"""
Flystroll command parser.
Converts structured command dicts into waypoint adjustments.
"""

from __future__ import annotations

VALID_COMMANDS = {"FOLLOW", "AVOID_LEFT", "AVOID_RIGHT", "CLIMB", "HOVER", "REPLAN", "DESCEND"}


def parse_to_waypoint_update(command: str, param: str, current_wp: dict) -> dict:
    """
    Given a Flystroll command and current waypoint, return a modified waypoint dict.
    current_wp: {"lat": float, "lng": float, "alt": float, "phase": str}
    """
    update = dict(current_wp)
    update["flystroll_command"] = command
    update["flystroll_param"] = param

    try:
        val = float(param)
    except (ValueError, TypeError):
        val = 0.0

    if command == "FOLLOW":
        update["speed"] = val

    elif command == "AVOID_LEFT":
        # Shift ~val meters west (approximate; proper impl needs bearing)
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
    """Convenience wrapper: apply a Flystroll API response to the current waypoint."""
    return parse_to_waypoint_update(
        event.get("command", "FOLLOW"),
        event.get("param", "0.5"),
        current_wp,
    )
