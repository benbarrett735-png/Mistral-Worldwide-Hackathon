"""Shared configuration for Louise safety drone system."""

import os
from dotenv import load_dotenv

load_dotenv()

# Mistral API — use general models with advanced prompts; fine-tuned IDs can override via env
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_VISION_MODEL = os.getenv("MISTRAL_VISION_MODEL", "pixtral-12b-2409")  # vision for Helpstral/Flystral
MISTRAL_GENERAL_MODEL = os.getenv("MISTRAL_GENERAL_MODEL", "mistral-large-latest")  # text/path decisions
HELPSTRAL_MODEL_ID = os.getenv("HELPSTRAL_MODEL_ID", MISTRAL_VISION_MODEL)
FLYSTRAL_MODEL_ID = os.getenv("FLYSTRAL_MODEL_ID", MISTRAL_VISION_MODEL)

# Routing — OSRM public (no key needed), ORS as fallback
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1"
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org/v2"

# Paris — drone centre hard-set at the Louvre (all drones depart and return here)
PARIS_CENTER = {"lat": 48.8566, "lng": 2.3522}
DRONE_HUB = {"lat": 48.8606, "lng": 2.3376, "label": "Louise Drone Centre — Louvre, Paris"}

# Flight parameters
HUB_TO_USER_ALT = 60   # metres AGL — approach (higher, faster transit)
TRACK_ALT = 25         # metres AGL — escort altitude (live follow)
HOME_ALT = 60          # metres AGL — return altitude
TAKEOFF_ALT = 10       # metres AGL — initial takeoff
APPROACH_RETURN_SPEED = 50  # m/s — to/from user and return to hub (fast)
ESCORT_SPEED = 12      # m/s — during live follow (smooth, safe)
CRUISE_SPEED = 50      # m/s — used for ETA; actual speed set per-phase in connector
LOITER_RADIUS = 0      # 0 = straight lines (copter mode)
FOLLOW_DISTANCE_M = 15 # metres behind user during live escort

# ArduPilot — SITL or real drone (connection string from env for real hardware)
SITL_HOST = os.getenv("SITL_HOST", "127.0.0.1")
SITL_PORT = int(os.getenv("SITL_PORT", "5760"))
# For real drone: set MAV_CONNECTION e.g. tcp:192.168.1.10:5760 or serial:/dev/ttyUSB0:57600
# When MAV_CONNECTION is set: server skips SITL start and EKF wait; connector uses this string.
MAV_CONNECTION = os.getenv("MAV_CONNECTION") or None
if MAV_CONNECTION is not None:
    MAV_CONNECTION = MAV_CONNECTION.strip() or None


def _env_warnings():
    """Log warnings for common config issues (call once at app startup if desired)."""
    import sys
    if MAV_CONNECTION and not MISTRAL_API_KEY:
        print("Config: MAV_CONNECTION is set (real drone) but MISTRAL_API_KEY is missing; Helpstral/Flystral will use fallbacks.", file=sys.stderr)
    if not MISTRAL_API_KEY:
        print("Config: MISTRAL_API_KEY not set; vision APIs will return safe fallbacks.", file=sys.stderr)
