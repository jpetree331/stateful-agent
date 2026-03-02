"""
Weather tool using Open-Meteo — no API key required.

Open-Meteo is a free, reliable weather API. Replaces wttr.in which was timing out.
Default location is configurable via AGENT_LOCATION env var.
"""
from __future__ import annotations

import os

import httpx
from langchain_core.tools import tool

_DEFAULT_LOCATION = os.environ.get("AGENT_LOCATION", "New York")
_TIMEOUT = 15

# WMO weather codes (Open-Meteo) → human-readable
_WMO_CODES = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Dense drizzle", 56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _wmo_desc(code: int) -> str:
    return _WMO_CODES.get(int(code), f"Weather code {code}")


def _c_to_f(c: float) -> int:
    return round(c * 9 / 5 + 32)


def _kmh_to_mph(kmh: float) -> float:
    return round(kmh * 0.621371, 1)


def _wind_dir(deg: float) -> str:
    """Convert degrees to compass direction."""
    dirs = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()
    idx = round(deg / 22.5) % 16
    return dirs[idx]


@tool
def get_weather(location: str = "") -> str:
    """
    Get the current weather and a 3-day forecast for any location.

    No API key needed. Uses the Open-Meteo service.
    Includes temperature (°F), humidity, wind, and conditions.

    Args:
        location: City name or zip code (e.g., "Boston", "10001", "Paris, France").
                  Defaults to the configured AGENT_LOCATION env var.
                  Leave blank for the default location.
    """
    loc = location.strip() or _DEFAULT_LOCATION
    try:
        # Geocode location
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": loc, "count": 1},
            timeout=_TIMEOUT,
        )
        geo.raise_for_status()
        geo_data = geo.json()
        if not geo_data.get("results"):
            return f"Weather: Could not find location '{loc}'."
        r = geo_data["results"][0]
        lat, lon = r["latitude"], r["longitude"]
        place = r.get("name", loc)
        tz = r.get("timezone", "America/New_York")

        # Fetch forecast
        resp = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                "timezone": tz,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return f"Weather fetch timed out for '{loc}'."
    except Exception as e:
        return f"Weather fetch failed for '{loc}': {e}"

    try:
        cur = data["current"]
        temp_c = cur["temperature_2m"]
        temp_f = _c_to_f(temp_c)
        humidity = cur["relative_humidity_2m"]
        wind_kmh = cur["wind_speed_10m"]
        wind_mph = _kmh_to_mph(wind_kmh)
        wind_deg = cur["wind_direction_10m"]
        wind_dir = _wind_dir(wind_deg)
        desc = _wmo_desc(cur["weather_code"])

        lines = [f"=== Weather: {place} ===\n"]
        lines.append(f"Now: {desc}, {temp_f}°F")
        lines.append(f"Humidity: {humidity}%  |  Wind: {wind_mph} mph {wind_dir}\n")

        # 3-day forecast
        daily = data["daily"]
        lines.append("Forecast:")
        for i in range(min(3, len(daily["time"]))):
            date = daily["time"][i][:10]  # YYYY-MM-DD
            max_c = daily["temperature_2m_max"][i]
            min_c = daily["temperature_2m_min"][i]
            code = daily["weather_code"][i]
            day_desc = _wmo_desc(code)
            lines.append(f"  {date}: {day_desc}, {_c_to_f(min_c)}°F – {_c_to_f(max_c)}°F")

        return "\n".join(lines)

    except (KeyError, IndexError) as e:
        return f"Weather data parse error: {e}\nRaw: {str(data)[:500]}"
