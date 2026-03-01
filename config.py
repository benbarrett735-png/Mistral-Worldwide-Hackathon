"""Shared configuration for Louise safety drone system."""

import os
from dotenv import load_dotenv

load_dotenv()

# Mistral API
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_VISION_MODEL = os.getenv("MISTRAL_VISION_MODEL", "pixtral-12b-2409")       # Helpstral base
MISTRAL_EDGE_MODEL = os.getenv("MISTRAL_EDGE_MODEL", "ministral-3b-latest")        # Flystral base (fast vision)
MISTRAL_GENERAL_MODEL = os.getenv("MISTRAL_GENERAL_MODEL", "mistral-large-latest") # text/path decisions
MISTRAL_FAST_MODEL = os.getenv("MISTRAL_FAST_MODEL", "mistral-small-latest")       # Louise chat

# Fine-tuned model endpoints (served from HuggingFace models via Colab GPU)
# Flystral: BenBarr/flystral — LoRA fine-tuned Ministral 3B
# Helpstral: (HuggingFace model, served similarly)
FLYSTRAL_ENDPOINT = os.getenv("FLYSTRAL_ENDPOINT", "")
HELPSTRAL_ENDPOINT = os.getenv("HELPSTRAL_ENDPOINT", "")

# Routing — OSRM public (no key needed), ORS as fallback
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1"
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org/v2"

# Multi-city hubs — each city has a drone centre, map centre, geofence, and search config
CITY_HUBS = {
    "paris": {
        "name": "Paris",
        "hub": {"lat": 48.8606, "lng": 2.3376, "label": "Louise Drone Centre — Louvre, Paris"},
        "center": {"lat": 48.8566, "lng": 2.3522},
        "bounds": {"lat_min": 48.80, "lat_max": 48.92, "lng_min": 2.22, "lng_max": 2.47},
        "country": "fr",
        "viewbox": "2.2,48.92,2.47,48.80",
        "zoom": 14,
    },
    "dublin": {
        "name": "Dublin",
        "hub": {"lat": 53.3441, "lng": -6.2675, "label": "Louise Drone Centre — Trinity College, Dublin"},
        "center": {"lat": 53.3498, "lng": -6.2603},
        "bounds": {"lat_min": 53.28, "lat_max": 53.42, "lng_min": -6.40, "lng_max": -6.10},
        "country": "ie",
        "viewbox": "-6.40,53.42,-6.10,53.28",
        "zoom": 14,
    },
    "london": {
        "name": "London",
        "hub": {"lat": 51.5014, "lng": -0.1419, "label": "Louise Drone Centre — Buckingham Palace, London"},
        "center": {"lat": 51.5074, "lng": -0.1278},
        "bounds": {"lat_min": 51.40, "lat_max": 51.60, "lng_min": -0.30, "lng_max": 0.10},
        "country": "gb",
        "viewbox": "-0.30,51.60,0.10,51.40",
        "zoom": 13,
    },
    "kilcoole": {
        "name": "Kilcoole (Demo Site)",
        "hub": {"lat": 53.1076, "lng": -6.0483, "label": "Louise Drone Centre — Kilcoole, Wicklow (Demo Site)"},
        "center": {"lat": 53.1076, "lng": -6.0483},
        "bounds": {"lat_min": 53.07, "lat_max": 53.14, "lng_min": -6.12, "lng_max": -6.00},
        "country": "ie",
        "viewbox": "-6.12,53.14,-6.00,53.07",
        "zoom": 15,
    },
}

DEFAULT_CITY = os.getenv("DEFAULT_CITY", "paris")
DRONE_HUB = CITY_HUBS[DEFAULT_CITY]["hub"]
PARIS_CENTER = CITY_HUBS["paris"]["center"]

GEOFENCE_BOUNDS = CITY_HUBS[DEFAULT_CITY]["bounds"]

# Pricing — distance-based (e.g. €3 base + per km)
BASE_PRICE_EUR = float(os.getenv("BASE_PRICE_EUR", "1.50"))
PRICE_PER_KM_EUR = float(os.getenv("PRICE_PER_KM_EUR", "0.25"))
CURRENCY = os.getenv("PRICE_CURRENCY", "EUR")

# Simulated battery when real telemetry has no battery (SITL often reports -1)
SIMULATE_BATTERY = os.getenv("SIMULATE_BATTERY", "1").strip().lower() in ("1", "true", "yes")
SIMULATED_BATTERY_START_PCT = int(os.getenv("SIMULATED_BATTERY_START_PCT", "100"))

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
