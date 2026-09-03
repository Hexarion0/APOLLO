"""
apollo/tools/internet.py — Internet access tools for APOLLO.

Tools:
  - WebSearchTool   : DuckDuckGo search (no API key required)
  - FetchURLTool    : Fetch and extract text content from any URL
  - GetWeatherTool  : Current weather via Open-Meteo (no API key required)
"""

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlencode

import aiohttp
from bs4 import BeautifulSoup

from apollo.tools.base import BaseTool

logger = logging.getLogger("apollo.tools.internet")

# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def _get(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> str:
    """Perform an async GET request and return the response text."""
    merged_headers = {**_DEFAULT_HEADERS, **(headers or {})}
    async with aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT, headers=merged_headers) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.text()


# ---------------------------------------------------------------------------
# WebSearchTool
# ---------------------------------------------------------------------------

class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo HTML endpoint (no API key required)."""

    name = "web_search"
    description = (
        "Search the web for current information using DuckDuckGo. "
        "Returns a list of relevant results with titles, URLs, and snippets. "
        "Use this when you need up-to-date information that may not be in your training data."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5, max: 10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5, **kwargs: Any) -> Dict[str, Any]:
        max_results = min(max(1, max_results), 10)
        logger.info(f"WebSearchTool: searching for '{query}' (max_results={max_results})")

        url = "https://html.duckduckgo.com/html/"
        params = {"q": query, "kl": "wt-wt"}

        try:
            raw_html = await _get(url, params=params)
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Web search request failed: {e}") from e

        soup = BeautifulSoup(raw_html, "html.parser")
        results: List[Dict[str, str]] = []

        for result_div in soup.select(".result"):
            if len(results) >= max_results:
                break

            title_tag = result_div.select_one(".result__title a")
            snippet_tag = result_div.select_one(".result__snippet")

            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")

            # DuckDuckGo wraps redirect URLs — try to extract the real URL
            real_url = _extract_ddg_url(href)

            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

            if title and real_url:
                results.append({"title": title, "url": real_url, "snippet": snippet})

        return {
            "query": query,
            "result_count": len(results),
            "results": results,
        }


def _extract_ddg_url(href: str) -> str:
    """Extract the actual destination URL from a DuckDuckGo redirect href."""
    if not href:
        return ""
    # DuckDuckGo redirect format: //duckduckgo.com/l/?uddg=<encoded_url>&...
    match = re.search(r"uddg=([^&]+)", href)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))
    # Fall back to the href as-is if not a redirect
    if href.startswith("http"):
        return href
    return ""


# ---------------------------------------------------------------------------
# FetchURLTool
# ---------------------------------------------------------------------------

class FetchURLTool(BaseTool):
    """Fetch and extract readable text content from any URL."""

    name = "fetch_url"
    description = (
        "Fetch the content of a URL and return it as readable plain text. "
        "Strips HTML tags, scripts, and styles. Useful for reading articles, "
        "documentation pages, or any web page content."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (must begin with http:// or https://)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters of text to return (default: 8000)",
                "default": 8000,
            },
        },
        "required": ["url"],
    }

    async def execute(self, url: str, max_chars: int = 8000, **kwargs: Any) -> Dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL scheme. Only http:// and https:// are allowed. Got: {url!r}")

        logger.info(f"FetchURLTool: fetching '{url}' (max_chars={max_chars})")
        max_chars = min(max(500, max_chars), 32000)

        try:
            raw_html = await _get(url)
        except aiohttp.ClientResponseError as e:
            raise RuntimeError(f"HTTP {e.status} error fetching {url}: {e.message}") from e
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Failed to fetch URL: {e}") from e

        # Parse and extract readable text
        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars] + "\n\n... [content truncated]"

        return {
            "url": url,
            "char_count": len(text),
            "truncated": truncated,
            "content": text,
        }


# ---------------------------------------------------------------------------
# GetWeatherTool
# ---------------------------------------------------------------------------

# WMO Weather Interpretation Codes (WW codes) — subset
_WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class GetWeatherTool(BaseTool):
    """Get current weather conditions for any location using Open-Meteo (free, no API key)."""

    name = "get_weather"
    description = (
        "Get the current weather conditions for a given city or location. "
        "Returns temperature, wind speed, humidity, and weather description. "
        "No API key required."
    )
    parameters = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name or location (e.g. 'Bangkok', 'London, UK', 'New York')",
            },
            "units": {
                "type": "string",
                "description": "Temperature unit: 'celsius' or 'fahrenheit' (default: celsius)",
                "enum": ["celsius", "fahrenheit"],
                "default": "celsius",
            },
        },
        "required": ["location"],
    }

    async def execute(self, location: str, units: str = "celsius", **kwargs: Any) -> Dict[str, Any]:
        logger.info(f"GetWeatherTool: looking up weather for '{location}' ({units})")

        # Step 1: Geocode the location
        try:
            geo_text = await _get(_GEOCODING_URL, params={"name": location, "count": 1, "language": "en", "format": "json"})
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Geocoding request failed: {e}") from e

        geo_data = json.loads(geo_text)
        geo_results = geo_data.get("results")
        if not geo_results:
            raise ValueError(f"Location not found: {location!r}. Try a more specific city name.")

        place = geo_results[0]
        lat = place["latitude"]
        lon = place["longitude"]
        display_name = f"{place.get('name', location)}, {place.get('country', '')}"

        # Step 2: Fetch current weather
        temp_unit = "fahrenheit" if units == "fahrenheit" else "celsius"
        wind_unit = "mph" if units == "fahrenheit" else "kmh"

        forecast_params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,wind_direction_10m,weathercode,precipitation",
            "temperature_unit": temp_unit,
            "wind_speed_unit": wind_unit,
            "timezone": "auto",
        }

        try:
            wx_text = await _get(_FORECAST_URL, params=forecast_params)
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Weather forecast request failed: {e}") from e

        wx_data = json.loads(wx_text)
        current = wx_data.get("current", {})
        current_units = wx_data.get("current_units", {})

        weather_code = current.get("weathercode", 0)
        description = _WMO_CODES.get(weather_code, f"Weather code {weather_code}")
        temp_symbol = "°F" if units == "fahrenheit" else "°C"
        speed_symbol = "mph" if units == "fahrenheit" else "km/h"

        return {
            "location": display_name,
            "latitude": lat,
            "longitude": lon,
            "timezone": wx_data.get("timezone", ""),
            "description": description,
            "temperature": f"{current.get('temperature_2m', 'N/A')}{temp_symbol}",
            "feels_like": f"{current.get('apparent_temperature', 'N/A')}{temp_symbol}",
            "humidity": f"{current.get('relative_humidity_2m', 'N/A')}%",
            "wind_speed": f"{current.get('wind_speed_10m', 'N/A')} {speed_symbol}",
            "wind_direction_deg": current.get("wind_direction_10m"),
            "precipitation": f"{current.get('precipitation', 0)} mm",
        }
