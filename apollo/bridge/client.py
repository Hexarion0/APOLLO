"""
apollo/bridge/client.py — APOLLO Session Bridge Client.

Used by desktop tools (TakeScreenshotTool, MediaControlTool) to call the
user-session bridge over localhost HTTP rather than trying to talk to Wayland
directly from the headless systemd service.
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("apollo.bridge.client")

DEFAULT_BRIDGE_URL = "http://127.0.0.1:7734"
_CONNECT_TIMEOUT = 2.0   # seconds — fast-fail if bridge is not running
_REQUEST_TIMEOUT = 20.0  # seconds — allow time for screenshot capture


class BridgeClient:
    """Async HTTP client for the APOLLO session bridge."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        connect_timeout: float = _CONNECT_TIMEOUT,
        request_timeout: float = _REQUEST_TIMEOUT,
    ):
        self.base_url = (base_url or os.getenv("APOLLO_BRIDGE_URL", DEFAULT_BRIDGE_URL)).rstrip("/")
        self.token = token or os.getenv("APOLLO_BRIDGE_TOKEN", "")
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["X-Apollo-Token"] = self.token
        return h

    async def is_available(self) -> bool:
        """Return True if the bridge server is reachable."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=self.connect_timeout),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def screenshot(self, region: str = "fullscreen") -> Dict[str, Any]:
        """
        Ask the bridge to capture a screenshot.

        Returns dict with keys: ok, path, size_kb, region
        or: error (str) on failure.
        """
        return await self._post("/screenshot", {"region": region})

    async def media(self, action: str, value: Optional[str] = None, player: Optional[str] = None) -> Dict[str, Any]:
        """
        Send a media/volume action to the bridge.

        Returns dict with ok (bool) and action-specific fields.
        """
        payload: Dict[str, Any] = {"action": action}
        if value is not None:
            payload["value"] = value
        if player is not None:
            payload["player"] = player
        return await self._post("/media", payload)

    async def notify(self, title: str, body: str, urgency: str = "normal") -> Dict[str, Any]:
        """Send a desktop notification via the bridge."""
        return await self._post("/notify", {"title": title, "body": body, "urgency": urgency})

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import aiohttp
        except ImportError:
            return {"error": "aiohttp not installed — cannot reach bridge"}

        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(
                        connect=self.connect_timeout,
                        total=self.request_timeout,
                    ),
                ) as resp:
                    data = await resp.json()
                    if resp.status >= 400 and "error" not in data:
                        data["error"] = f"HTTP {resp.status}"
                    return data
        except Exception as e:
            logger.debug(f"Bridge request to {url} failed: {e}")
            return {"error": str(e)}


# Module-level default instance (lazy-created tools share this)
_default_client: Optional[BridgeClient] = None


def get_client() -> BridgeClient:
    global _default_client
    if _default_client is None:
        _default_client = BridgeClient()
    return _default_client
