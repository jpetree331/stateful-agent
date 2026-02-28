"""
Weather tool using wttr.in — no API key required.

wttr.in is a free, public weather service that returns structured JSON.
Default location is configurable via AGENT_LOCATION env var.
"""
from __future__ import annotations

import os

import httpx
from langchain_core.tools import tool

_DEFAULT_LOCATION = os.environ.get("AGENT_LOCATION", "New York")
_TIMEOUT = 10


def _desc_code(code: str) -> str:
    """Map wttr.in weather code to human-readable description."""
    codes = {
        "113": "Sunny", "116": "Partly cloudy", "119": "Cloudy",
        "122": "Overcast", "143": "Mist", "176": "Patchy rain",
        "179": "Patchy snow", "200": "Thundery outbreaks", "227": "Blowing snow",
        "230": "Blizzard", "248": "Fog", "260": "Freezing fog",
        "263": "Light drizzle", "266": "Light drizzle", "281": "Freezing drizzle",
        "284": "Heavy freezing drizzle", "293": "Light rain", "296": "Light rain",
        "299": "Moderate rain", "302": "Moderate rain", "305": "Heavy rain",
        "308": "Heavy rain", "311": "Light freezing rain", "314": "Moderate freezing rain",
        "317": "Light sleet", "320": "Moderate sleet", "323": "Light snow",
        "326": "Light snow", "329": "Moderate snow", "332": "Moderate snow",
        "335": "Heavy snow", "338": "Heavy snow", "350": "Ice pellets",
        "353": "Light rain shower", "356": "Moderate rain shower",
        "359": "Heavy rain shower", "362": "Light sleet shower",
        "365": "Moderate sleet shower", "368": "Light snow shower",
        "371": "Moderate snow shower", "374": "Light ice pellet shower",
        "377": "Moderate ice pellet shower", "386": "Light rain + thunder",
        "389": "Moderate rain + thunder", "392": "Light snow + thunder",
        "395": "Moderate snow + thunder",
    }
    return codes.get(str(code), f"Code {code}")


@tool
def get_weather(location: str = "") -> str:
    """
    Get the current weather and a 3-day forecast for any location.

    No API key needed. Uses the public wttr.in service.
    Includes temperature (°F), feels-like, humidity, wind, UV index, and conditions.

    Args:
        location: City name, address, or zip code (e.g., "Boston", "10001", "Paris, France").
                  Defaults to the configured AGENT_LOCATION env var (currently: the user's area).
                  Leave blank for the default location.
    """
    loc = location.strip() or _DEFAULT_LOCATION
    try:
        resp = httpx.get(
            f"https://wttr.in/{loc}",
            params={"format": "j1"},
            headers={"User-Agent": "LangGraphAgent/1.0"},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return f"Weather fetch failed for '{loc}': {e}"

    try:
        cur = data["current_condition"][0]
        temp_f = cur["temp_F"]
        feels_f = cur["FeelsLikeF"]
        humidity = cur["humidity"]
        wind_mph = cur["windspeedMiles"]
        wind_dir = cur["winddir16Point"]
        uv = cur["uvIndex"]
        desc = cur["weatherDesc"][0]["value"]
        visibility = cur["visibility"]

        lines = [f"=== Weather: {loc} ===\n"]
        lines.append(f"Now: {desc}, {temp_f}°F (feels like {feels_f}°F)")
        lines.append(f"Humidity: {humidity}%  |  Wind: {wind_mph} mph {wind_dir}  |  UV: {uv}  |  Visibility: {visibility} mi\n")

        # 3-day forecast
        lines.append("Forecast:")
        for day in data.get("weather", [])[:3]:
            date = day["date"]
            max_f = day["maxtempF"]
            min_f = day["mintempF"]
            day_desc = day["hourly"][4]["weatherDesc"][0]["value"]  # noon conditions
            rain_mm = day["hourly"][4].get("precipMM", "0")
            lines.append(f"  {date}: {day_desc}, {min_f}°F – {max_f}°F, precip {rain_mm}mm")

        return "\n".join(lines)

    except (KeyError, IndexError) as e:
        return f"Weather data parse error: {e}\nRaw: {str(data)[:500]}"
