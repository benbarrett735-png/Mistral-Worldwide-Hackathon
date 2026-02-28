"""
Geo-intelligence module — real data from OpenStreetMap APIs.

Replaces hardcoded stub tools with actual queries:
- Overpass API: streetlights, lit roads, POIs, building density
- Nominatim: reverse geocoding for neighborhood/area identification
- Route safety scoring based on real lighting infrastructure data

All queries are cached per session to avoid hammering public APIs.
"""

from __future__ import annotations

import json
import time
import math
from datetime import datetime
from functools import lru_cache
from typing import Optional

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
REQUEST_TIMEOUT = 10.0
USER_AGENT = "LouiseSafetyDrone/1.0 (hackathon project)"

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 300  # 5 minutes


def _cached(key: str) -> dict | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _store(key: str, data: dict) -> dict:
    _cache[key] = (time.time(), data)
    return data


# ── Overpass queries ──────────────────────────────────────────────────────────

def _overpass_query(query: str) -> dict | None:
    try:
        resp = httpx.post(OVERPASS_URL, data={"data": query}, timeout=REQUEST_TIMEOUT,
                          headers={"User-Agent": USER_AGENT})
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def count_streetlights(lat: float, lng: float, radius_m: int = 300) -> int:
    """Count streetlights (highway=street_lamp) within radius of a point."""
    cache_key = f"lights:{lat:.4f},{lng:.4f},{radius_m}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached.get("count", 0)

    query = f"""
    [out:json][timeout:10];
    node["highway"="street_lamp"](around:{radius_m},{lat},{lng});
    out count;
    """
    data = _overpass_query(query)
    count = 0
    if data and "elements" in data:
        for el in data["elements"]:
            if el.get("tags", {}).get("total"):
                count = int(el["tags"]["total"])
                break
            count += 1

    _store(cache_key, {"count": count})
    return count


def count_lit_roads(lat: float, lng: float, radius_m: int = 300) -> dict:
    """Count roads tagged lit=yes vs lit=no within radius."""
    cache_key = f"litroads:{lat:.4f},{lng:.4f},{radius_m}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    query = f"""
    [out:json][timeout:10];
    (
      way["highway"]["lit"](around:{radius_m},{lat},{lng});
    );
    out tags;
    """
    data = _overpass_query(query)
    lit_yes = 0
    lit_no = 0
    lit_unknown = 0
    if data and "elements" in data:
        for el in data["elements"]:
            lit_val = el.get("tags", {}).get("lit", "")
            if lit_val == "yes":
                lit_yes += 1
            elif lit_val == "no":
                lit_no += 1
            else:
                lit_unknown += 1

    result = {"lit_yes": lit_yes, "lit_no": lit_no, "lit_unknown": lit_unknown,
              "total_roads": lit_yes + lit_no + lit_unknown}
    return _store(cache_key, result)


def get_nearby_pois(lat: float, lng: float, radius_m: int = 200) -> dict:
    """Get counts of safety-relevant POIs: shops, restaurants, police, hospitals."""
    cache_key = f"pois:{lat:.4f},{lng:.4f},{radius_m}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    query = f"""
    [out:json][timeout:10];
    (
      node["amenity"~"restaurant|cafe|bar|pub|fast_food"](around:{radius_m},{lat},{lng});
      node["shop"](around:{radius_m},{lat},{lng});
      node["amenity"~"police|hospital|clinic|pharmacy"](around:{radius_m},{lat},{lng});
      node["tourism"~"hotel|hostel"](around:{radius_m},{lat},{lng});
    );
    out tags;
    """
    data = _overpass_query(query)
    food_drink = 0
    shops = 0
    emergency = 0
    accommodation = 0

    if data and "elements" in data:
        for el in data["elements"]:
            tags = el.get("tags", {})
            amenity = tags.get("amenity", "")
            if amenity in ("restaurant", "cafe", "bar", "pub", "fast_food"):
                food_drink += 1
            elif amenity in ("police", "hospital", "clinic", "pharmacy"):
                emergency += 1
            elif tags.get("shop"):
                shops += 1
            elif tags.get("tourism") in ("hotel", "hostel"):
                accommodation += 1

    result = {
        "food_drink": food_drink, "shops": shops,
        "emergency_services": emergency, "accommodation": accommodation,
        "total": food_drink + shops + emergency + accommodation,
    }
    return _store(cache_key, result)


# ── Nominatim reverse geocoding ──────────────────────────────────────────────

def reverse_geocode(lat: float, lng: float) -> dict:
    """Get real neighborhood name, area type, and address from coordinates."""
    cache_key = f"geo:{lat:.4f},{lng:.4f}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    try:
        resp = httpx.get(
            NOMINATIM_URL,
            params={
                "lat": lat, "lon": lng,
                "format": "jsonv2", "addressdetails": 1, "extratags": 1,
                "zoom": 16,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return _store(cache_key, {"error": f"HTTP {resp.status_code}"})

        data = resp.json()
        address = data.get("address", {})
        result = {
            "display_name": data.get("display_name", "Unknown"),
            "neighborhood": address.get("suburb") or address.get("neighbourhood") or address.get("quarter") or "Unknown",
            "city": address.get("city") or address.get("town") or address.get("village") or "Unknown",
            "road": address.get("road", "Unknown"),
            "osm_type": data.get("type", "unknown"),
            "category": data.get("category", "unknown"),
        }
        return _store(cache_key, result)

    except Exception as e:
        return _store(cache_key, {"error": str(e), "neighborhood": "Unknown"})


# ── Composite scoring ────────────────────────────────────────────────────────

def compute_area_safety_score(lat: float, lng: float) -> dict:
    """
    Compute a real safety score for an area based on actual OSM data:
    - Streetlight density
    - Lit road percentage
    - POI density (natural surveillance from foot traffic)
    - Time of day
    - Reverse geocoded area info
    """
    cache_key = f"safety:{lat:.4f},{lng:.4f}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    light_count = count_streetlights(lat, lng, 300)
    lit_roads = count_lit_roads(lat, lng, 300)
    pois = get_nearby_pois(lat, lng, 200)
    geo = reverse_geocode(lat, lng)

    hour = datetime.now().hour
    is_night = hour < 6 or hour >= 20
    is_evening = 17 <= hour < 20

    # Lighting score (0-10): streetlight density + lit road ratio
    if lit_roads["total_roads"] > 0:
        lit_ratio = lit_roads["lit_yes"] / lit_roads["total_roads"]
    else:
        lit_ratio = 0.5 if light_count > 5 else 0.2

    light_density = min(light_count / 20.0, 1.0)  # 20+ streetlights in 300m = max
    lighting_score = (lit_ratio * 0.6 + light_density * 0.4) * 10

    # Foot traffic score (0-10): POI density as proxy
    poi_density = min(pois["total"] / 15.0, 1.0)  # 15+ POIs = max
    traffic_score = poi_density * 10

    # Emergency access score (0-10)
    emergency_score = min(pois["emergency_services"] * 3, 10)

    # Time penalty
    time_modifier = -2.0 if is_night else -0.5 if is_evening else 0.0

    # Weighted composite
    raw_score = (
        lighting_score * 0.40 +
        traffic_score * 0.30 +
        emergency_score * 0.15 +
        5.0 * 0.15  # baseline
    ) + time_modifier

    safety_score = max(1, min(10, round(raw_score)))

    if lighting_score >= 7:
        lighting_quality = "good"
    elif lighting_score >= 4:
        lighting_quality = "moderate"
    else:
        lighting_quality = "poor"

    if traffic_score >= 6:
        foot_traffic = "high"
    elif traffic_score >= 3:
        foot_traffic = "moderate"
    else:
        foot_traffic = "low"

    result = {
        "safety_score": safety_score,
        "lighting_quality": lighting_quality,
        "foot_traffic_level": foot_traffic,
        "streetlights_nearby": light_count,
        "lit_roads": lit_roads,
        "pois_nearby": pois["total"],
        "emergency_services_nearby": pois["emergency_services"],
        "neighborhood": geo.get("neighborhood", "Unknown"),
        "road": geo.get("road", "Unknown"),
        "time_of_day": "night" if is_night else "evening" if is_evening else "day",
        "scoring_breakdown": {
            "lighting": round(lighting_score, 1),
            "foot_traffic": round(traffic_score, 1),
            "emergency_access": round(emergency_score, 1),
            "time_modifier": time_modifier,
        },
    }
    return _store(cache_key, result)


def compute_route_safety(from_lat: float, from_lng: float, to_lat: float, to_lng: float) -> dict:
    """
    Score a route by sampling points along it and averaging safety scores.
    Identifies the weakest segment.
    """
    n_samples = 5
    samples = []
    worst_segment = None
    worst_score = 11

    for i in range(n_samples):
        t = i / max(1, n_samples - 1)
        lat = from_lat + (to_lat - from_lat) * t
        lng = from_lng + (to_lng - from_lng) * t
        score_data = compute_area_safety_score(lat, lng)
        s = score_data["safety_score"]
        samples.append({
            "segment": i + 1,
            "lat": round(lat, 5), "lng": round(lng, 5),
            "score": s,
            "neighborhood": score_data["neighborhood"],
            "lighting": score_data["lighting_quality"],
        })
        if s < worst_score:
            worst_score = s
            worst_segment = samples[-1]

    avg_score = round(sum(s["score"] for s in samples) / len(samples))
    dist_km = _haversine(from_lat, from_lng, to_lat, to_lng)
    walk_minutes = int(dist_km * 1000 / 80)  # ~80m/min walking

    return {
        "overall_safety_score": max(1, min(10, avg_score)),
        "distance_km": round(dist_km, 2),
        "estimated_walk_minutes": walk_minutes,
        "segments": samples,
        "weakest_segment": worst_segment,
        "recommendation": (
            "Route appears safe for walking"
            if avg_score >= 6
            else "Some segments have limited lighting — consider a drone escort"
            if avg_score >= 4
            else "This route has poor lighting and low foot traffic — drone escort recommended"
        ),
    }


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
