"""
apollo/tools/desktop.py — Desktop & Workstation Control tools for APOLLO.

Tools:
  - TakeScreenshotTool : Capture screenshots via grim/grimblast (Wayland/Hyprland) with direct upload support.
  - MediaControlTool   : Control media & Spotify playback via playerctl and system volume via wpctl.
  - SystemPowerTool    : Workstation lock, display sleep, suspend, reboot, and power control.

When running as a headless systemd service (no Wayland socket), tools automatically
delegate to the apollo-bridge user-session companion process over localhost HTTP.
If the bridge is unavailable they fall back to direct execution (for session-local use).
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from apollo.bridge.client import get_client as _get_bridge
from apollo.channels.base import BaseChannel
from apollo.tools.base import BaseTool

logger = logging.getLogger("apollo.tools.desktop")

# Default screenshot directory
SCREENSHOT_DIR = Path.home() / "Pictures" / "Screenshots"


class TakeScreenshotTool(BaseTool):
    """Capture a screenshot of the current display using grim or grimblast (Wayland/Hyprland)."""

    name = "take_screenshot"
    description = (
        "Capture a screenshot of the current screen, a specific monitor, or the active window. "
        "Returns the path to the saved screenshot file and can upload it directly to the chat. "
        "Works on Wayland with grim/grimblast."
    )
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "string",
                "description": (
                    "What to capture. Options: 'fullscreen' (entire screen/all monitors), "
                    "'active' (active window only), 'area' (interactive region select). "
                    "Defaults to 'fullscreen'."
                ),
                "enum": ["fullscreen", "active", "area"],
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Optional custom file path for the screenshot. "
                    "Defaults to ~/Pictures/Screenshots/screenshot_<timestamp>.png"
                ),
            },
            "upload": {
                "type": "boolean",
                "description": "Whether to send/upload the captured screenshot image directly to the owner in chat. Defaults to true.",
            },
        },
        "required": [],
    }

    def __init__(
        self,
        channel: Optional[BaseChannel] = None,
        owner_id: Optional[str] = None,
    ):
        self.channel = channel
        self.owner_id = owner_id

    async def execute(
        self,
        region: str = "fullscreen",
        output_path: Optional[str] = None,
        upload: bool = True,
    ) -> str:
        # ── Try bridge first (works from headless systemd service) ──────────
        bridge = _get_bridge()
        if await bridge.is_available():
            result = await bridge.screenshot(region=region)
            if result.get("ok"):
                save_path = Path(result["path"])
                size_kb = result.get("size_kb", save_path.stat().st_size / 1024 if save_path.exists() else 0)
                msg = (
                    f"📸 **Screenshot Captured** *(via session bridge)*\n"
                    f"Path: `{save_path}`\n"
                    f"Size: `{size_kb:.1f} KB` | Region: `{region}`"
                )
                if upload and self.channel and self.owner_id:
                    try:
                        await self.channel.send_photo(
                            recipient_id=str(self.owner_id),
                            photo_path=str(save_path),
                            caption=f"🖥️ Screen Capture ({region}) — {size_kb:.1f} KB",
                        )
                        msg += "\n*Uploaded directly to Telegram chat.*"
                    except Exception as e:
                        logger.warning(f"Could not upload screenshot to channel: {e}")
                return msg
            else:
                # Bridge responded but reported an error
                return f"❌ Screenshot failed: {result.get('error', 'Unknown bridge error')}"

        # ── Fallback: direct grim/grimblast (only works in user session) ────
        if output_path:
            save_path = Path(output_path).expanduser().resolve()
        else:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = SCREENSHOT_DIR / f"screenshot_{timestamp}.png"

        save_path.parent.mkdir(parents=True, exist_ok=True)

        grimblast = await self._which("grimblast")
        grim = await self._which("grim")

        if grimblast:
            cmd = await self._build_grimblast_cmd(region, str(save_path))
        elif grim:
            cmd = await self._build_grim_cmd(region, str(save_path))
        else:
            return (
                "❌ Bridge unavailable and neither 'grimblast' nor 'grim' found.\n"
                "Make sure apollo-bridge is running in your Hyprland session:\n"
                "`systemctl --user start apollo-bridge`"
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

            if proc.returncode != 0:
                err = stderr.decode().strip()
                return f"Error capturing screenshot (exit {proc.returncode}): {err}"

            if not save_path.exists():
                return f"Screenshot command succeeded but file not found at {save_path}"

            size_kb = save_path.stat().st_size / 1024
            msg = (
                f"📸 **Screenshot Captured**\n"
                f"Path: `{save_path}`\n"
                f"Size: `{size_kb:.1f} KB` | Region: `{region}`"
            )

            if upload and self.channel and self.owner_id:
                try:
                    await self.channel.send_photo(
                        recipient_id=str(self.owner_id),
                        photo_path=str(save_path),
                        caption=f"🖥️ Screen Capture ({region}) — {size_kb:.1f} KB",
                    )
                    msg += "\n*Uploaded directly to Telegram chat.*"
                except Exception as e:
                    logger.warning(f"Could not upload screenshot to channel: {e}")

            return msg

        except asyncio.TimeoutError:
            return "Error: Screenshot capture timed out (15s)."
        except Exception as e:
            logger.error(f"Screenshot capture error: {e}")
            return f"Error capturing screenshot: {e}"


    async def _which(self, binary: str) -> Optional[str]:
        """Check if a binary exists in PATH."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "which", binary,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode().strip()
        except Exception:
            pass
        return None

    async def _build_grimblast_cmd(self, region: str, output: str) -> list:
        """Build grimblast command for the given capture region."""
        if region == "active":
            return ["grimblast", "save", "active", output]
        elif region == "area":
            return ["grimblast", "save", "area", output]
        else:  # fullscreen
            return ["grimblast", "save", "screen", output]

    async def _build_grim_cmd(self, region: str, output: str) -> list:
        """Build grim command for the given capture region."""
        if region == "active":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c",
                    "hyprctl activewindow -j | jq -r '\"\\(.at[0]),\\(.at[1]) \\(.size[0])x\\(.size[1])\"'",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await proc.communicate()
                geometry = stdout.decode().strip()
                if geometry and proc.returncode == 0:
                    return ["grim", "-g", geometry, output]
            except Exception:
                pass
            return ["grim", output]
        elif region == "area":
            return ["bash", "-c", f"grim -g \"$(slurp)\" {output}"]
        else:  # fullscreen
            return ["grim", output]


class MediaControlTool(BaseTool):
    """Control media playback (Spotify, MPRIS) via playerctl and system volume via wpctl (PipeWire)."""

    name = "media_control"
    description = (
        "Control media playback and Spotify (play, pause, next, previous, stop, status, shuffle, loop, seek, open track/playlist URI) "
        "and control system audio volume (volume-get, volume-set, mute, unmute, mute-toggle) via PipeWire/wpctl."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "The action to perform.\n"
                    "Media/Spotify Actions: 'play', 'pause', 'play-pause', 'next', 'previous', 'stop', 'status', 'shuffle', 'loop', 'seek', 'open'.\n"
                    "Volume Actions: 'volume-get', 'volume-set', 'mute', 'unmute', 'mute-toggle'."
                ),
                "enum": [
                    "play", "pause", "play-pause", "next", "previous", "stop", "status",
                    "shuffle", "loop", "seek", "open",
                    "volume-get", "volume-set", "mute", "unmute", "mute-toggle",
                ],
            },
            "value": {
                "type": "string",
                "description": (
                    "Argument for specific actions:\n"
                    "- For 'volume-set': e.g. '75%', '+5%', '-10%', '0.8'\n"
                    "- For 'seek': offset in seconds or target e.g. '+15', '-10', '120'\n"
                    "- For 'shuffle': 'on', 'off', or 'toggle'\n"
                    "- For 'loop': 'track', 'playlist', 'none', or 'toggle'\n"
                    "- For 'open': Spotify URI or URL (e.g. 'spotify:track:...' or 'https://open.spotify.com/...')"
                ),
            },
            "player": {
                "type": "string",
                "description": (
                    "Optional specific player name (e.g. 'spotify', 'firefox', 'mpv', 'chromium'). "
                    "Defaults to 'spotify' if active, otherwise most recently active player."
                ),
            },
        },
        "required": ["action"],
    }

    async def execute(
        self,
        action: str,
        value: Optional[str] = None,
        player: Optional[str] = None,
    ) -> str:
        action = action.strip().lower()

        # ── Try bridge first ────────────────────────────────────────────────
        bridge = _get_bridge()
        if await bridge.is_available():
            result = await bridge.media(action=action, value=value, player=player)
            if "error" in result:
                return f"❌ Media bridge error: {result['error']}"
            return self._format_bridge_media_result(action, result)

        # ── Fallback: direct calls (works in user session) ──────────────────
        # Volume actions via wpctl
        if action.startswith("volume") or action in ("mute", "unmute", "mute-toggle"):
            return await self._handle_volume(action, value)

        # Media & Spotify actions via playerctl
        return await self._handle_media(action, value, player)

    def _format_bridge_media_result(self, action: str, data: dict) -> str:
        """Format a bridge media response into a human-readable string."""
        if action == "status":
            status = data.get("status", "")
            title = data.get("title", "Unknown Track")
            artist = data.get("artist", "Unknown Artist")
            album = data.get("album", "")
            shuffle = data.get("shuffle", "")
            loop = data.get("loop", "")

            try:
                pos_sec = float(data.get("position", 0) or 0)
                len_us = float(data.get("length", 0) or 0)
                len_sec = len_us / 1_000_000.0 if len_us > 1000 else len_us
                if len_sec > 0:
                    fraction = min(1.0, pos_sec / len_sec)
                    bar_len = 10
                    filled = int(round(fraction * bar_len))
                    bar = "█" * filled + "░" * (bar_len - filled)
                    pos_fmt = f"{int(pos_sec // 60):02d}:{int(pos_sec % 60):02d}"
                    len_fmt = f"{int(len_sec // 60):02d}:{int(len_sec % 60):02d}"
                    progress = f"[{bar}] {pos_fmt} / {len_fmt}"
                else:
                    progress = ""
            except Exception:
                progress = ""

            status_emoji = "▶️ Playing" if status.lower() == "playing" else "⏸️ Paused" if status.lower() == "paused" else f"⏹️ {status}"
            lines = [
                f"🎵 **{title}**",
                f"👤 **{artist}**" + (f" • *{album}*" if album else ""),
                f"📊 {status_emoji}" + (f" | `{progress}`" if progress else ""),
            ]
            extras = []
            if shuffle and shuffle != "Off":
                extras.append(f"🔀 Shuffle: `{shuffle}`")
            if loop and loop != "None":
                extras.append(f"🔁 Loop: `{loop}`")
            if extras:
                lines.append(" • ".join(extras))
            return "\n".join(lines)

        elif action in ("play", "pause", "play-pause", "next", "previous", "stop"):
            title = data.get("title", "")
            artist = data.get("artist", "")
            status = data.get("status", "")
            status_emoji = "▶️ Playing" if status.lower() == "playing" else "⏸️ Paused" if status.lower() == "paused" else f"⏹️ {status}"
            lines = [f"✅ **Media {action.capitalize()}**"]
            if title:
                lines.append(f"🎵 **{title}**" + (f" — {artist}" if artist else ""))
            lines.append(f"📊 {status_emoji}")
            return "\n".join(lines)

        elif action == "shuffle":
            return f"🔀 **Shuffle**: `{data.get('shuffle', 'updated')}`"

        elif action == "loop":
            return f"🔁 **Loop**: `{data.get('loop', 'updated')}`"

        elif action == "volume-get":
            return f"🔊 **System Volume**: {data.get('result', 'unknown')}"

        elif action in ("volume-set", "mute-toggle"):
            result = data.get("result", "")
            muted = "[MUTED]" in (result or "")
            if action == "mute-toggle":
                return f"{'🔇 Muted' if muted else '🔊 Unmuted'}. Volume: `{result or 'unknown'}`"
            return f"🔊 Volume updated. Current: `{result or 'unknown'}`"

        elif action == "mute":
            return "🔇 System audio **muted**."

        elif action == "unmute":
            return "🔊 System audio **unmuted**."

        elif action == "seek":
            return f"⏩ **Seeked** | Position: `{data.get('position', 'updated')}`"

        elif action == "open":
            return "🎶 Opened media URI."

        return f"✅ Action `{action}` executed."

    async def _handle_media(self, action: str, value: Optional[str], player: Optional[str]) -> str:
        """Handle media playback actions via playerctl."""
        playerctl = await self._run_cmd(["which", "playerctl"])
        if playerctl is None:
            return "Error: 'playerctl' not found. Install with: sudo pacman -S playerctl"

        target_player = player
        if not target_player:
            # Check if spotify is running among players
            active_players = await self._run_cmd(["playerctl", "-l"])
            if active_players and "spotify" in active_players.lower():
                target_player = "spotify"

        base_cmd = ["playerctl"]
        if target_player:
            base_cmd.extend(["--player", target_player])

        if action == "status":
            return await self._get_media_status(base_cmd, target_player)

        elif action in ("play", "pause", "play-pause", "next", "previous", "stop"):
            res = await self._run_cmd(base_cmd + [action])
            if res is None:
                return f"Error: Failed to execute media action '{action}' on player '{target_player or 'default'}'."
            # Get updated track info
            status = await self._get_media_status(base_cmd, target_player)
            return f"✅ **Media {action.capitalize()}**\n\n{status}"

        elif action == "shuffle":
            shuffle_val = (value or "toggle").lower()
            if shuffle_val in ("on", "true", "yes", "1"):
                arg = "on"
            elif shuffle_val in ("off", "false", "no", "0"):
                arg = "off"
            else:
                arg = "toggle"
            await self._run_cmd(base_cmd + ["shuffle", arg])
            current = await self._run_cmd(base_cmd + ["shuffle"])
            return f"🔀 **Shuffle**: `{current or arg}`"

        elif action == "loop":
            loop_val = (value or "toggle").lower()
            if loop_val in ("track", "single", "one"):
                arg = "track"
            elif loop_val in ("playlist", "all"):
                arg = "playlist"
            elif loop_val in ("none", "off"):
                arg = "none"
            else:
                # Toggle
                curr = await self._run_cmd(base_cmd + ["loop"])
                arg = "track" if curr == "None" else "none"

            await self._run_cmd(base_cmd + ["loop", arg])
            current = await self._run_cmd(base_cmd + ["loop"])
            return f"🔁 **Loop**: `{current or arg}`"

        elif action == "seek":
            if not value:
                return "Error: 'value' parameter required for seek (e.g. '+15', '-10', or '120')."
            seek_val = value.strip()
            # playerctl position 10+ / 10- or position 120
            if seek_val.startswith("+"):
                cmd = base_cmd + ["position", f"{seek_val[1:]}+"]
            elif seek_val.startswith("-"):
                cmd = base_cmd + ["position", f"{seek_val[1:]}-"]
            else:
                cmd = base_cmd + ["position", seek_val]

            await self._run_cmd(cmd)
            pos = await self._run_cmd(base_cmd + ["metadata", "--format", "{{ duration(position) }} / {{ duration(mpris:length) }}"])
            return f"⏩ **Seeked**: `{seek_val}` | Position: `{pos or 'updated'}`"

        elif action == "open":
            if not value:
                return "Error: 'value' parameter required for open action (e.g. Spotify URI 'spotify:track:...' or web URL)."
            uri = value.strip()
            # Try playerctl open first
            res = await self._run_cmd(base_cmd + ["open", uri])
            if res is None:
                # Fallback to xdg-open or spotify binary
                await self._run_cmd(["xdg-open", uri])
            return f"🎶 Opened media URI: `{uri}`"

        return f"Error: Unknown media action '{action}'."

    async def _get_media_status(self, base_cmd: list, player_name: Optional[str]) -> str:
        """Get currently playing media metadata with progress bar."""
        # Check player status
        status = await self._run_cmd(base_cmd + ["status"])
        if status is None or "No players found" in (status or ""):
            return "No active media player detected."

        status_emoji = "▶️ Playing" if status.lower() == "playing" else "⏸️ Paused" if status.lower() == "paused" else f"⏹️ {status}"

        # Metadata
        artist = await self._run_cmd(base_cmd + ["metadata", "artist"]) or "Unknown Artist"
        title = await self._run_cmd(base_cmd + ["metadata", "title"]) or "Unknown Track"
        album = await self._run_cmd(base_cmd + ["metadata", "album"]) or ""

        # Position & length in seconds
        pos_raw = await self._run_cmd(base_cmd + ["position"])
        len_raw = await self._run_cmd(base_cmd + ["metadata", "mpris:length"])

        progress_str = ""
        try:
            if pos_raw and len_raw:
                pos_sec = float(pos_raw)
                len_sec = float(len_raw) / 1_000_000.0  # mpris:length is in microseconds
                if len_sec > 0:
                    fraction = min(1.0, max(0.0, pos_sec / len_sec))
                    bar_len = 10
                    filled = int(round(fraction * bar_len))
                    bar = "█" * filled + "░" * (bar_len - filled)
                    pos_fmt = f"{int(pos_sec // 60):02d}:{int(pos_sec % 60):02d}"
                    len_fmt = f"{int(len_sec // 60):02d}:{int(len_sec % 60):02d}"
                    progress_str = f"[{bar}] {pos_fmt} / {len_fmt}"
        except Exception:
            pass

        if not progress_str:
            pos_formatted = await self._run_cmd(
                base_cmd + ["metadata", "--format", "{{ duration(position) }} / {{ duration(mpris:length) }}"]
            )
            if pos_formatted:
                progress_str = pos_formatted

        # Additional flags
        shuffle_state = await self._run_cmd(base_cmd + ["shuffle"])
        loop_state = await self._run_cmd(base_cmd + ["loop"])

        lines = [
            f"🎵 **{title}**",
            f"👤 **{artist}**" + (f" • *{album}*" if album else ""),
            f"📊 {status_emoji}" + (f" | `{progress_str}`" if progress_str else ""),
        ]

        extras = []
        if player_name:
            extras.append(f"Player: `{player_name}`")
        if shuffle_state and shuffle_state != "Off":
            extras.append(f"🔀 Shuffle: `{shuffle_state}`")
        if loop_state and loop_state != "None":
            extras.append(f"🔁 Loop: `{loop_state}`")

        if extras:
            lines.append(" • ".join(extras))

        return "\n".join(lines)

    async def _handle_volume(self, action: str, value: Optional[str]) -> str:
        """Handle volume actions via wpctl (PipeWire/WirePlumber)."""
        wpctl = await self._run_cmd(["which", "wpctl"])
        if wpctl is None:
            return "Error: 'wpctl' not found. Install WirePlumber: sudo pacman -S wireplumber"

        sink_id = "@DEFAULT_AUDIO_SINK@"

        if action == "volume-get":
            result = await self._run_cmd(["wpctl", "get-volume", sink_id])
            if result:
                return f"🔊 **System Volume**: {result}"
            return "Error: Could not retrieve volume."

        elif action == "volume-set":
            if not value:
                return "Error: 'value' parameter required for volume-set (e.g. '75%' or '+5%')."

            vol_arg = value.strip()
            result = await self._run_cmd(["wpctl", "set-volume", sink_id, vol_arg])
            if result is not None:
                current = await self._run_cmd(["wpctl", "get-volume", sink_id])
                return f"🔊 Volume set to `{vol_arg}`. Current: `{current or 'unknown'}`"
            return f"Error: Failed to set volume to '{vol_arg}'."

        elif action == "mute":
            await self._run_cmd(["wpctl", "set-mute", sink_id, "1"])
            return "🔇 System audio **muted**."

        elif action == "unmute":
            await self._run_cmd(["wpctl", "set-mute", sink_id, "0"])
            return "🔊 System audio **unmuted**."

        elif action == "mute-toggle":
            await self._run_cmd(["wpctl", "set-mute", sink_id, "toggle"])
            result = await self._run_cmd(["wpctl", "get-volume", sink_id])
            muted = "[MUTED]" in (result or "")
            return f"{'🔇 Muted' if muted else '🔊 Unmuted'}. Volume: `{result or 'unknown'}`"

        return f"Error: Unknown volume action '{action}'."

    async def _run_cmd(self, cmd: list) -> Optional[str]:
        """Run a command and return stdout, or None on failure."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                return stdout.decode().strip()
            return None
        except asyncio.TimeoutError:
            logger.warning(f"Command timed out: {' '.join(cmd)}")
            return None
        except Exception as e:
            logger.error(f"Command error ({' '.join(cmd)}): {e}")
            return None


class SystemPowerTool(BaseTool):
    """Workstation lock, display sleep, suspend, reboot, and power control."""

    name = "system_power"
    description = (
        "Execute workstation power, lock, and display state actions. "
        "Actions: 'lock' (locks session), 'screen-off' (turns off displays), "
        "'screen-on' (turns on displays), 'suspend' (sleeps workstation), "
        "'hibernate', 'reboot', 'shutdown'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "The power/session action to perform.",
                "enum": [
                    "lock",
                    "screen-off",
                    "screen-on",
                    "suspend",
                    "hibernate",
                    "reboot",
                    "shutdown",
                ],
            },
        },
        "required": ["action"],
    }

    async def execute(self, action: str) -> str:
        action = action.strip().lower()

        if action == "lock":
            # Try hyprlock, swaylock, loginctl lock-session
            for cmd in [["hyprlock"], ["swaylock"], ["loginctl", "lock-session"]]:
                which = await self._which(cmd[0])
                if which:
                    asyncio.create_task(self._run_bg(cmd))
                    return "🔒 Workstation session **locked**."
            return "Error: No screenlocker found (checked hyprlock, swaylock, loginctl)."

        elif action in ("screen-off", "dpms-off"):
            # Wayland Hyprland dpms off
            hyprctl = await self._which("hyprctl")
            if hyprctl:
                res = await self._run_cmd(["hyprctl", "dispatch", "dpms", "off"])
                return f"💤 Displays turned **off** (dpms off): {res or 'OK'}"
            wlopm = await self._which("wlopm")
            if wlopm:
                await self._run_cmd(["wlopm", "--off", "*"])
                return "💤 Displays turned **off** via wlopm."
            return "Error: Could not find hyprctl or wlopm to toggle displays."

        elif action in ("screen-on", "dpms-on"):
            hyprctl = await self._which("hyprctl")
            if hyprctl:
                res = await self._run_cmd(["hyprctl", "dispatch", "dpms", "on"])
                return f"🖥️ Displays turned **on** (dpms on): {res or 'OK'}"
            wlopm = await self._which("wlopm")
            if wlopm:
                await self._run_cmd(["wlopm", "--on", "*"])
                return "🖥️ Displays turned **on** via wlopm."
            return "Error: Could not find hyprctl or wlopm to toggle displays."

        elif action in ("suspend", "sleep"):
            systemctl = await self._which("systemctl")
            if not systemctl:
                return "Error: 'systemctl' not found."
            asyncio.create_task(self._run_bg(["systemctl", "suspend"]))
            return "🌙 Workstation entering **suspend / sleep mode**."

        elif action == "hibernate":
            systemctl = await self._which("systemctl")
            if not systemctl:
                return "Error: 'systemctl' not found."
            asyncio.create_task(self._run_bg(["systemctl", "hibernate"]))
            return "❄️ Workstation entering **hibernation**."

        elif action == "reboot":
            systemctl = await self._which("systemctl")
            if not systemctl:
                return "Error: 'systemctl' not found."
            asyncio.create_task(self._run_bg(["systemctl", "reboot"]))
            return "🔄 Workstation **reboot initiated**."

        elif action in ("shutdown", "poweroff"):
            systemctl = await self._which("systemctl")
            if not systemctl:
                return "Error: 'systemctl' not found."
            asyncio.create_task(self._run_bg(["systemctl", "poweroff"]))
            return "🛑 Workstation **poweroff initiated**."

        return f"Error: Unknown power action '{action}'."

    async def _which(self, binary: str) -> Optional[str]:
        """Check if a binary exists in PATH."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "which", binary,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode().strip()
        except Exception:
            pass
        return None

    async def _run_cmd(self, cmd: list) -> Optional[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            if proc.returncode == 0:
                return stdout.decode().strip()
            return None
        except Exception:
            return None

    async def _run_bg(self, cmd: list) -> None:
        """Run system control command after brief delay to allow response to send."""
        await asyncio.sleep(0.5)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env={**os.environ},
            )
            await proc.wait()
        except Exception as e:
            logger.error(f"Error running background power command {cmd}: {e}")
