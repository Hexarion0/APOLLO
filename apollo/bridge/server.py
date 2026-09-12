"""
apollo/bridge/server.py — APOLLO Session Bridge Server.

A tiny HTTP server that runs INSIDE the user's graphical session
(Hyprland/Wayland), giving the headless apollo.service access to
Wayland-native capabilities:

  - POST /screenshot     → grim/grimblast → returns PNG bytes or path
  - POST /media          → playerctl / wpctl actions
  - POST /notify         → libnotify desktop notification
  - GET  /health         → liveness probe

Start with:
    python -m apollo.bridge.server
or via the user-level systemd service: apollo-bridge.service
"""

import asyncio
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from aiohttp import web
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger("apollo.bridge.server")

DEFAULT_PORT = 7734
DEFAULT_TOKEN = os.getenv("APOLLO_BRIDGE_TOKEN", "")

SCREENSHOT_DIR = Path.home() / "Pictures" / "Screenshots"


def _check_token(request) -> bool:
    """Validate shared secret token if configured."""
    if not DEFAULT_TOKEN:
        return True  # No auth configured → open (localhost-only anyway)
    auth = request.headers.get("X-Apollo-Token", "")
    return auth == DEFAULT_TOKEN


async def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode().strip(), stderr.decode().strip()
    except asyncio.TimeoutError:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


async def _which(binary: str) -> str | None:
    rc, out, _ = await _run(["which", binary], timeout=3)
    return out if rc == 0 and out else None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_health(request):
    return web.json_response({"status": "ok", "service": "apollo-bridge"})


async def handle_screenshot(request):
    if not _check_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json() if request.content_length else {}
    region = data.get("region", "fullscreen")

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = SCREENSHOT_DIR / f"screenshot_{timestamp}.png"

    grimblast = await _which("grimblast")
    grim = await _which("grim")

    if grimblast:
        region_map = {"fullscreen": "screen", "active": "active", "area": "area"}
        cmd = ["grimblast", "save", region_map.get(region, "screen"), str(save_path)]
    elif grim:
        if region == "active":
            # Get active window geometry via hyprctl
            rc, geo, _ = await _run(
                ["bash", "-c",
                 "hyprctl activewindow -j | jq -r '\"\\(.at[0]),\\(.at[1]) \\(.size[0])x\\(.size[1])\"'"]
            )
            if rc == 0 and geo:
                cmd = ["grim", "-g", geo, str(save_path)]
            else:
                cmd = ["grim", str(save_path)]
        elif region == "area":
            # Non-interactive fallback — grab fullscreen instead
            cmd = ["grim", str(save_path)]
        else:
            cmd = ["grim", str(save_path)]
    else:
        return web.json_response({
            "error": "Neither grimblast nor grim found. Install: sudo pacman -S grim grimblast-git"
        }, status=503)

    rc, _, err = await _run(cmd, timeout=15)

    if rc != 0:
        return web.json_response({"error": f"Screenshot failed (exit {rc}): {err}"}, status=500)

    if not save_path.exists():
        return web.json_response({"error": "Screenshot command succeeded but file missing"}, status=500)

    size_kb = save_path.stat().st_size / 1024
    return web.json_response({
        "ok": True,
        "path": str(save_path),
        "size_kb": round(size_kb, 1),
        "region": region,
    })


async def handle_media(request):
    if not _check_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    action = data.get("action", "").strip().lower()
    value = data.get("value")
    player = data.get("player")

    # Volume actions via wpctl
    if action.startswith("volume") or action in ("mute", "unmute", "mute-toggle"):
        sink = "@DEFAULT_AUDIO_SINK@"
        if action == "volume-get":
            rc, out, _ = await _run(["wpctl", "get-volume", sink])
            return web.json_response({"ok": rc == 0, "result": out})
        elif action == "volume-set" and value:
            rc, _, _ = await _run(["wpctl", "set-volume", sink, value])
            rc2, out2, _ = await _run(["wpctl", "get-volume", sink])
            return web.json_response({"ok": rc == 0, "result": out2})
        elif action == "mute":
            rc, _, _ = await _run(["wpctl", "set-mute", sink, "1"])
            return web.json_response({"ok": rc == 0})
        elif action == "unmute":
            rc, _, _ = await _run(["wpctl", "set-mute", sink, "0"])
            return web.json_response({"ok": rc == 0})
        elif action == "mute-toggle":
            rc, _, _ = await _run(["wpctl", "set-mute", sink, "toggle"])
            rc2, out2, _ = await _run(["wpctl", "get-volume", sink])
            return web.json_response({"ok": rc == 0, "result": out2})

    # Playerctl actions
    if not player:
        rc, out, _ = await _run(["playerctl", "-l"])
        if rc == 0 and "spotify" in out.lower():
            player = "spotify"

    base = ["playerctl"]
    if player:
        base += ["--player", player]

    if action == "status":
        tasks = [
            _run(base + ["status"]),
            _run(base + ["metadata", "artist"]),
            _run(base + ["metadata", "title"]),
            _run(base + ["metadata", "album"]),
            _run(base + ["position"]),
            _run(base + ["metadata", "mpris:length"]),
            _run(base + ["shuffle"]),
            _run(base + ["loop"]),
        ]
        results = await asyncio.gather(*tasks)
        return web.json_response({
            "ok": True,
            "status": results[0][1],
            "artist": results[1][1],
            "title": results[2][1],
            "album": results[3][1],
            "position": results[4][1],
            "length": results[5][1],
            "shuffle": results[6][1],
            "loop": results[7][1],
        })

    elif action in ("play", "pause", "play-pause", "next", "previous", "stop"):
        rc, _, _ = await _run(base + [action])
        # Grab updated status
        rc2, st, _ = await _run(base + ["status"])
        rc3, ti, _ = await _run(base + ["metadata", "title"])
        rc4, ar, _ = await _run(base + ["metadata", "artist"])
        return web.json_response({
            "ok": rc == 0,
            "status": st,
            "title": ti,
            "artist": ar,
        })

    elif action == "shuffle":
        arg = value or "toggle"
        await _run(base + ["shuffle", arg])
        rc, out, _ = await _run(base + ["shuffle"])
        return web.json_response({"ok": True, "shuffle": out})

    elif action == "loop":
        arg = value or "toggle"
        await _run(base + ["loop", arg])
        rc, out, _ = await _run(base + ["loop"])
        return web.json_response({"ok": True, "loop": out})

    elif action == "seek" and value:
        if value.startswith("+"):
            cmd = base + ["position", f"{value[1:]}+"]
        elif value.startswith("-"):
            cmd = base + ["position", f"{value[1:]}-"]
        else:
            cmd = base + ["position", value]
        rc, _, _ = await _run(cmd)
        rc2, pos, _ = await _run(base + ["position"])
        return web.json_response({"ok": rc == 0, "position": pos})

    elif action == "open" and value:
        rc, _, _ = await _run(base + ["open", value])
        if rc != 0:
            await _run(["xdg-open", value])
        return web.json_response({"ok": True})

    return web.json_response({"error": f"Unknown action: {action}"}, status=400)


async def handle_notify(request):
    if not _check_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    title = data.get("title", "APOLLO")
    body = data.get("body", "")
    urgency = data.get("urgency", "normal")

    rc, _, _ = await _run(["notify-send", "-u", urgency, title, body], timeout=5)
    return web.json_response({"ok": rc == 0})


# ---------------------------------------------------------------------------
# App factory & entrypoint
# ---------------------------------------------------------------------------

def create_app() -> "web.Application":
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/screenshot", handle_screenshot)
    app.router.add_post("/media", handle_media)
    app.router.add_post("/notify", handle_notify)
    return app


def main():
    if not AIOHTTP_AVAILABLE:
        raise RuntimeError(
            "aiohttp is required for the bridge server. "
            "Install with: pip install aiohttp"
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    port = int(os.getenv("APOLLO_BRIDGE_PORT", str(DEFAULT_PORT)))
    host = os.getenv("APOLLO_BRIDGE_HOST", "127.0.0.1")

    app = create_app()
    logger.info(f"APOLLO Bridge Server starting on http://{host}:{port}")
    web.run_app(app, host=host, port=port, access_log=None)


if __name__ == "__main__":
    main()
