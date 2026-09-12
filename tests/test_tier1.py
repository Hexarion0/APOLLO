"""
Unit and integration tests for Tier 1 features:
  - TakeScreenshotTool (with channel photo upload)
  - MediaControlTool (Spotify, playback, volume, shuffle, loop, seek, open, progress bar)
  - SystemPowerTool (lock, screen-off, screen-on, suspend, reboot, shutdown)
  - Natural Language Reminders (SetReminderTool, ListRemindersTool, CancelReminderTool)
  - Gateway reminder alert handling
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apollo.channels.base import BaseChannel
from apollo.policy import PermissionTier, PolicyEngine
from apollo.scheduler.cron import BackgroundScheduler
from apollo.tools.desktop import MediaControlTool, SystemPowerTool, TakeScreenshotTool
from apollo.tools.reminders import (
    CancelReminderTool,
    ListRemindersTool,
    SetReminderTool,
    parse_time_spec_to_seconds,
)


# ---------------------------------------------------------------------------
# Time Parser Tests
# ---------------------------------------------------------------------------

class TestReminderTimeParsing:
    """Test parse_time_spec_to_seconds utility."""

    def test_pure_seconds(self):
        assert parse_time_spec_to_seconds("60") == 60
        assert parse_time_spec_to_seconds("300") == 300

    def test_relative_minutes(self):
        assert parse_time_spec_to_seconds("35m") == 35 * 60
        assert parse_time_spec_to_seconds("10min") == 10 * 60
        assert parse_time_spec_to_seconds("5 minutes") == 5 * 60

    def test_relative_hours(self):
        assert parse_time_spec_to_seconds("2h") == 2 * 3600
        assert parse_time_spec_to_seconds("1hr") == 3600
        assert parse_time_spec_to_seconds("3 hours") == 3 * 3600

    def test_relative_seconds_unit(self):
        assert parse_time_spec_to_seconds("45s") == 45
        assert parse_time_spec_to_seconds("30 secs") == 30

    def test_compound_units(self):
        assert parse_time_spec_to_seconds("1h30m") == 90 * 60
        assert parse_time_spec_to_seconds("2h 15m 10s") == 2 * 3600 + 15 * 60 + 10

    def test_in_format(self):
        assert parse_time_spec_to_seconds("in 20 minutes") == 20 * 60
        assert parse_time_spec_to_seconds("in 2 hours") == 2 * 3600
        assert parse_time_spec_to_seconds("in 45 seconds") == 45

    def test_clock_time(self):
        # Setting clock time should return a positive integer representing seconds until that time
        sec = parse_time_spec_to_seconds("14:30")
        assert sec is not None
        assert sec > 0

    def test_invalid_format(self):
        assert parse_time_spec_to_seconds("someday maybe") is None
        assert parse_time_spec_to_seconds("") is None


# ---------------------------------------------------------------------------
# Reminder Tools Tests
# ---------------------------------------------------------------------------

class TestReminderTools:
    """Test SetReminderTool, ListRemindersTool, and CancelReminderTool."""

    @pytest.mark.asyncio
    async def test_set_reminder_execution(self):
        mock_scheduler = MagicMock()
        mock_scheduler.add_task = MagicMock()

        tool = SetReminderTool(scheduler=mock_scheduler)
        result = await tool.execute(text="Take out trash", time_spec="15m")

        assert "Reminder Set" in result
        assert "Take out trash" in result
        assert "15m 0s" in result
        mock_scheduler.add_task.assert_called_once()
        call_kwargs = mock_scheduler.add_task.call_args[1]
        assert call_kwargs["interval_seconds"] == 15 * 60
        assert call_kwargs["prompt"] == "Take out trash"
        assert call_kwargs["persist"] is True

    @pytest.mark.asyncio
    async def test_set_reminder_invalid_time(self):
        mock_scheduler = MagicMock()
        tool = SetReminderTool(scheduler=mock_scheduler)
        result = await tool.execute(text="Take out trash", time_spec="invalid_time")
        assert "Error" in result
        mock_scheduler.add_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_reminders(self):
        mock_scheduler = MagicMock()
        task1 = MagicMock(task_id="reminder_1234", prompt="Buy milk", interval_seconds=600)
        task2 = MagicMock(task_id="proactive_persona_checkin", prompt="Checkin", interval_seconds=3600)
        mock_scheduler.list_tasks.return_value = [task1, task2]

        tool = ListRemindersTool(scheduler=mock_scheduler)
        result = await tool.execute()

        assert "Active Reminders" in result
        assert "reminder_1234" in result
        assert "Buy milk" in result
        assert "proactive_persona_checkin" not in result

    @pytest.mark.asyncio
    async def test_cancel_reminder(self):
        mock_scheduler = MagicMock()
        mock_scheduler.remove_task.return_value = True

        tool = CancelReminderTool(scheduler=mock_scheduler)
        result = await tool.execute(reminder_id="reminder_1234")

        assert "Cancelled reminder" in result
        mock_scheduler.remove_task.assert_called_once_with("reminder_1234")


# ---------------------------------------------------------------------------
# Media & Spotify Remote Tests
# ---------------------------------------------------------------------------

class TestMediaAndSpotifyControl:
    """Test MediaControlTool playback, Spotify intelligence, and volume control."""

    @pytest.mark.asyncio
    async def test_media_playback_play(self):
        tool = MediaControlTool()
        with patch.object(tool, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = lambda cmd: "playerctl" if cmd[0] == "which" else "Playing" if "status" in cmd else "Track"
            result = await tool.execute(action="play")
            assert "Media Play" in result or "✅" in result

    @pytest.mark.asyncio
    async def test_media_shuffle_and_loop(self):
        tool = MediaControlTool()
        with patch.object(tool, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = lambda cmd: "playerctl" if cmd[0] == "which" else "On" if "shuffle" in cmd else "Track"
            result = await tool.execute(action="shuffle", value="on")
            assert "Shuffle" in result

            result_loop = await tool.execute(action="loop", value="track")
            assert "Loop" in result_loop

    @pytest.mark.asyncio
    async def test_media_seek(self):
        tool = MediaControlTool()
        with patch.object(tool, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = lambda cmd: "playerctl" if cmd[0] == "which" else "01:30 / 03:45"
            result = await tool.execute(action="seek", value="+15")
            assert "Seeked" in result
            assert "+15" in result

    @pytest.mark.asyncio
    async def test_media_open_uri(self):
        tool = MediaControlTool()
        with patch.object(tool, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = lambda cmd: "playerctl" if cmd[0] == "which" else "OK"
            result = await tool.execute(action="open", value="spotify:track:6rqhFgbbKwnb9MLmUQDhG6")
            assert "Opened media URI" in result
            assert "spotify:track" in result

    @pytest.mark.asyncio
    async def test_media_status_formatting_with_progress(self):
        tool = MediaControlTool()
        with patch.object(tool, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            def side_effect(cmd):
                if cmd[0] == "which":
                    return "playerctl"
                if "status" in cmd:
                    return "Playing"
                if "metadata" in cmd and "artist" in cmd:
                    return "Daft Punk"
                if "metadata" in cmd and "title" in cmd:
                    return "Get Lucky"
                if "metadata" in cmd and "album" in cmd:
                    return "Random Access Memories"
                if "position" in cmd:
                    return "90.0"
                if "mpris:length" in cmd:
                    return "240000000"  # 240 seconds
                if "shuffle" in cmd:
                    return "On"
                if "loop" in cmd:
                    return "None"
                return None

            mock_cmd.side_effect = side_effect
            status = await tool._get_media_status(["playerctl", "--player", "spotify"], "spotify")

            assert "Get Lucky" in status
            assert "Daft Punk" in status
            assert "Random Access Memories" in status
            assert "Playing" in status
            assert "█" in status  # Progress bar character
            assert "01:30 / 04:00" in status


# ---------------------------------------------------------------------------
# System Power Tests
# ---------------------------------------------------------------------------

class TestSystemPowerTool:
    """Test SystemPowerTool session lock, display power, suspend, reboot, shutdown."""

    def test_system_power_tool_schema(self):
        tool = SystemPowerTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "system_power"
        actions = schema["function"]["parameters"]["properties"]["action"]["enum"]
        assert "lock" in actions
        assert "screen-off" in actions
        assert "screen-on" in actions
        assert "suspend" in actions
        assert "reboot" in actions
        assert "shutdown" in actions

    @pytest.mark.asyncio
    async def test_lock_action(self):
        tool = SystemPowerTool()
        with patch.object(tool, "_which", new_callable=AsyncMock, return_value="/usr/bin/hyprlock"):
            with patch.object(tool, "_run_bg", new_callable=AsyncMock):
                result = await tool.execute(action="lock")
                assert "locked" in result.lower()

    @pytest.mark.asyncio
    async def test_screen_off_action(self):
        tool = SystemPowerTool()
        with patch.object(tool, "_which", new_callable=AsyncMock, return_value="/usr/bin/hyprctl"):
            with patch.object(tool, "_run_cmd", new_callable=AsyncMock, return_value="ok"):
                result = await tool.execute(action="screen-off")
                assert "off" in result.lower()

    @pytest.mark.asyncio
    async def test_suspend_action(self):
        tool = SystemPowerTool()
        with patch.object(tool, "_which", new_callable=AsyncMock, return_value="/usr/bin/systemctl"):
            with patch.object(tool, "_run_bg", new_callable=AsyncMock):
                result = await tool.execute(action="suspend")
                assert "suspend" in result.lower()


# ---------------------------------------------------------------------------
# Screen Capture Upload Tests
# ---------------------------------------------------------------------------

class TestScreenCaptureWithChannel:
    """Test TakeScreenshotTool uploading directly via channel."""

    @pytest.mark.asyncio
    async def test_screenshot_uploads_to_channel(self):
        with tempfile.TemporaryDirectory() as td:
            mock_channel = MagicMock()
            mock_channel.send_photo = AsyncMock()

            tool = TakeScreenshotTool(channel=mock_channel, owner_id="12345")
            output_file = Path(td) / "test_screen.png"
            output_file.write_bytes(b"PNGDATA")

            with patch.object(tool, "_which", new_callable=AsyncMock, return_value="/usr/bin/grim"):
                with patch("asyncio.create_subprocess_exec") as mock_exec:
                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
                    mock_exec.return_value = mock_proc

                    result = await tool.execute(output_path=str(output_file), upload=True)

                    assert "Screenshot Captured" in result
                    mock_channel.send_photo.assert_called_once_with(
                        recipient_id="12345",
                        photo_path=str(output_file.resolve()),
                        caption="🖥️ Screen Capture (fullscreen) — 0.0 KB",
                    )

    @pytest.mark.asyncio
    async def test_screenshot_uploads_with_channel_getter(self):
        with tempfile.TemporaryDirectory() as td:
            mock_channel = MagicMock()
            mock_channel.send_photo = AsyncMock()

            holder = {"channel": None}
            tool = TakeScreenshotTool(
                channel_getter=lambda: holder["channel"],
                owner_id="12345",
            )
            # Channel is attached AFTER tool creation (like in main.py)
            holder["channel"] = mock_channel

            output_file = Path(td) / "test_screen.png"
            output_file.write_bytes(b"PNGDATA")

            with patch.object(tool, "_which", new_callable=AsyncMock, return_value="/usr/bin/grim"):
                with patch("asyncio.create_subprocess_exec") as mock_exec:
                    mock_proc = MagicMock()
                    mock_proc.returncode = 0
                    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
                    mock_exec.return_value = mock_proc

                    result = await tool.execute(output_path=str(output_file), upload=True)

                    assert "Screenshot Captured" in result
                    assert "Uploaded directly" in result
                    mock_channel.send_photo.assert_called_once()



# ---------------------------------------------------------------------------
# Policy Tier Validation Tests
# ---------------------------------------------------------------------------

class TestTier1Policy:
    """Test policy.json tiers for Tier 1 tools."""

    def test_policy_tiers_for_tier1_tools(self):
        policy_file = Path("policy.json")
        engine = PolicyEngine(policy_path=policy_file)

        assert engine.get_tier("system_power") == PermissionTier.CONFIRM
        assert engine.get_tier("set_reminder") == PermissionTier.LOGGED
        assert engine.get_tier("list_reminders") == PermissionTier.AUTO
        assert engine.get_tier("cancel_reminder") == PermissionTier.AUTO
        assert engine.get_tier("media_control") == PermissionTier.AUTO
        assert engine.get_tier("take_screenshot") == PermissionTier.LOGGED
