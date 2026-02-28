"""Shared configuration for Louise safety drone system."""

import os
from dotenv import load_dotenv

load_dotenv()

# Mistral API
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
HELPSTROLL_MODEL_ID = os.getenv("HELPSTROLL_MODEL_ID", "pixtral-12b-2409")
FLYSTROLL_MODEL_ID = os.getenv("FLYSTROLL_MODEL_ID", "pixtral-12b-2409")

# OpenRouteService
ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org/v2"

# Paris map
PARIS_CENTER = {"lat": 48.8566, "lng": 2.3522}
DRONE_HUB = {"lat": 48.8809, "lng": 2.3553, "label": "Louise Hub - Gare du Nord"}

# Flight altitudes (metres above home)
HUB_TO_USER_ALT = 50
TRACK_ALT = 25
HOME_ALT = 50
