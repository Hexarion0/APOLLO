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


async def handle_pc_control(request):
    """Bridge endpoint for PCControlTool: mouse, keyboard, windows, apps."""
    if not _check_token(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    action = data.get("action", "").strip().lower()
    x = data.get("x")
    y = data.get("y")
    button = data.get("button", "left")
    text = data.get("text")
    keys = data.get("keys")
    direction = data.get("direction", "down")
    amount = int(data.get("amount", 3))

    ydotool = await _which("ydotool")
    hyprctl = await _which("hyprctl")

    BUTTON_MAP = {"left": "1", "middle": "2", "right": "3"}
    SCROLL_MAP = {"down": ("3", "3"), "up": ("3", "-3"), "right": ("2", "3"), "left": ("2", "-3")}

    if action == "mouse_move":
        if x is None or y is None:
            return web.json_response({"error": "mouse_move requires x and y"}, status=400)
        if not ydotool:
            return web.json_response({"error": "ydotool not found"}, status=503)
        rc, _, err = await _run([ydotool, "mousemove", "--x", str(x), "--y", str(y)])
        if rc != 0:
            return web.json_response({"error": f"mouse_move failed: {err}"}, status=500)
        return web.json_response({"ok": True, "message": f"🖱️ Mouse moved to `({x}, {y})`."})

    elif action == "mouse_click":
        if not ydotool:
            return web.json_response({"error": "ydotool not found"}, status=503)
        btn = BUTTON_MAP.get(button, "1")
        if x is not None and y is not None:
            rc, _, err = await _run([ydotool, "mousemove", "--x", str(x), "--y", str(y)])
            if rc != 0:
                return web.json_response({"error": f"mouse_move failed: {err}"}, status=500)
            await asyncio.sleep(0.05)
        rc, _, err = await _run([ydotool, "click", btn])
        if rc != 0:
            return web.json_response({"error": f"mouse_click failed: {err}"}, status=500)
        pos_str = f" at `({x}, {y})`" if x is not None and y is not None else ""
        return web.json_response({"ok": True, "message": f"🖱️ {button.capitalize()} click{pos_str}."})

    elif action == "mouse_scroll":
        if not ydotool:
            return web.json_response({"error": "ydotool not found"}, status=503)
        axis, base_val = SCROLL_MAP.get(direction, ("3", "3"))
        val = str(int(base_val) * max(1, amount) // 3) if amount != 3 else base_val
        rc, _, err = await _run([ydotool, "scroll", "--axis", axis, "--value", val])
        if rc != 0:
            key_map = {"down": "Next", "up": "Prior", "left": "Left", "right": "Right"}
            fallback_key = key_map.get(direction, "Next")
            for _ in range(min(amount, 10)):
                await _run([ydotool, "key", fallback_key])
            return web.json_response({"ok": True, "message": f"🖱️ Scrolled {direction} ×{amount} (key fallback)."})
        return web.json_response({"ok": True, "message": f"🖱️ Scrolled {direction} ×{amount}."})

    elif action == "key_press":
        if not keys:
            return web.json_response({"error": "key_press requires 'keys' parameter"}, status=400)
        if not ydotool:
            return web.json_response({"error": "ydotool not found"}, status=503)
        rc, _, err = await _run([ydotool, "key", keys])
        if rc != 0:
            return web.json_response({"error": f"key_press failed: {err}"}, status=500)
        return web.json_response({"ok": True, "message": f"⌨️ Pressed `{keys}`."})

    elif action == "type_text":
        if not text:
            return web.json_response({"error": "type_text requires 'text' parameter"}, status=400)
        if not ydotool:
            return web.json_response({"error": "ydotool not found"}, status=503)
        rc, _, err = await _run([ydotool, "type", "--delay", "30", "--", text])
        if rc != 0:
            return web.json_response({"error": f"type_text failed: {err}"}, status=500)
        preview = text[:50] + ("…" if len(text) > 50 else "")
        return web.json_response({"ok": True, "message": f"⌨️ Typed: `{preview}`"})

    elif action == "app_launch":
        if not text:
            return web.json_response({"error": "app_launch requires 'text' parameter"}, status=400)
        if hyprctl:
            rc, _, _ = await _run(["hyprctl", "dispatch", "exec", text])
            if rc == 0:
                return web.json_response({"ok": True, "message": f"🚀 Launched `{text}` via Hyprland."})
        try:
            subprocess.Popen(text.split(), env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return web.json_response({"ok": True, "message": f"🚀 Launched `{text}`."})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    elif action == "open_url":
        if not text:
            return web.json_response({"error": "open_url requires 'text' parameter"}, status=400)
        xdg = await _which("xdg-open")
        if xdg:
            rc, _, err = await _run([xdg, text])
            if rc == 0:
                return web.json_response({"ok": True, "message": f"🌐 Opened `{text}` in default browser."})
        for browser in ["zen-browser", "firefox", "brave"]:
            b = await _which(browser)
            if b:
                subprocess.Popen([b, text], env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return web.json_response({"ok": True, "message": f"🌐 Opened `{text}` in `{browser}`."})
        return web.json_response({"error": "No browser found to open URL"}, status=503)

    elif action == "window_focus":
        if not text:
            return web.json_response({"error": "window_focus requires 'text' parameter"}, status=400)
        if not hyprctl:
            return web.json_response({"error": "hyprctl not found"}, status=503)
        for match in [f"class:{text}", f"title:{text}", text]:
            rc, _, _ = await _run(["hyprctl", "dispatch", "focuswindow", match])
            if rc == 0:
                return web.json_response({"ok": True, "message": f"🪟 Focused window: `{text}`."})
        return web.json_response({"error": f"No window matching '{text}' found"}, status=404)

    elif action == "window_list":
        if not hyprctl:
            return web.json_response({"error": "hyprctl not found"}, status=503)
        rc, out, err = await _run(["hyprctl", "clients", "-j"])
        if rc != 0:
            return web.json_response({"error": f"hyprctl failed: {err}"}, status=500)
        import json as _json
        try:
            clients = _json.loads(out)
            lines = ["🪟 **Open Windows:**\n"]
            for c in clients:
                cls = c.get("class", "?")
                title = c.get("title", "")[:60]
                ws = c.get("workspace", {}).get("name", "?")
                lines.append(f"• `{cls}` — *{title}* (ws: {ws})")
            msg = "\n".join(lines) if len(lines) > 1 else "🪟 No open windows."
            return web.json_response({"ok": True, "message": msg})
        except Exception:
            return web.json_response({"ok": True, "message": f"🪟 Windows:\n```\n{out[:800]}\n```"})

    elif action == "get_cursor_pos":
        if hyprctl:
            rc, out, _ = await _run(["hyprctl", "cursorpos"])
            if rc == 0 and out:
                return web.json_response({"ok": True, "message": f"🖱️ Cursor position: `{out}`"})
        return web.json_response({"error": "hyprctl not available"}, status=503)

    return web.json_response({"error": f"Unknown action: {action}"}, status=400)


# ---------------------------------------------------------------------------
# App factory & entrypoint
# ---------------------------------------------------------------------------

def create_app() -> "web.Application":
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/screenshot", handle_screenshot)
    app.router.add_post("/media", handle_media)
    app.router.add_post("/notify", handle_notify)
    app.router.add_post("/pc_control", handle_pc_control)
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
