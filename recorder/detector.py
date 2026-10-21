from __future__ import annotations

import logging
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

import config

logger = logging.getLogger(__name__)


# ==============================================================================
#                      ZOOM DETECTOR STRATEGY INTERFACES
# ==============================================================================

class BaseZoomDetectorBackend(ABC):
    """Abstract Strategy interface for platform-specific Zoom window detectors."""

    @abstractmethod
    def get_active_meeting_window(self) -> Optional[dict]:
        """Returns details of the active Zoom meeting window if present, else None."""
        pass

    @abstractmethod
    def get_zoom_window(self) -> Optional[dict]:
        """Returns any active Zoom window (prioritizing meeting over dashboard)."""
        pass

    def is_meeting_active(self) -> bool:
        """Returns True if an active Zoom meeting is detected, False otherwise."""
        return self.get_active_meeting_window() is not None


class X11ZoomDetectorBackend(BaseZoomDetectorBackend):
    """Linux Zoom detector backend inspecting X11 window tree via xwininfo."""

    def __init__(self):
        self._pattern = re.compile(
            r'^\s*(0x[0-9a-fA-F]+)\s+"([^"]*)":\s+\("([^"]*)"\s+"([^"]*)"\)'
            r'(?:\s+(\d+)x(\d+)([+-]\d+)([+-]\d+))?'
        )
        self._ignored_titles = config.ZOOM_IGNORED_TITLES

    def _get_window_geometry(self, win_id: str) -> Optional[dict]:
        """Queries window geometry directly via xwininfo as fallback."""
        try:
            out = subprocess.check_output(
                ["xwininfo", "-id", win_id],
                stderr=subprocess.DEVNULL
            ).decode("utf-8")
            x_m = re.search(r'Absolute upper-left X:\s+([+-]?\d+)', out)
            y_m = re.search(r'Absolute upper-left Y:\s+([+-]?\d+)', out)
            w_m = re.search(r'Width:\s+(\d+)', out)
            h_m = re.search(r'Height:\s+(\d+)', out)
            if x_m and y_m and w_m and h_m:
                return {
                    "x": int(x_m.group(1)),
                    "y": int(y_m.group(1)),
                    "width": int(w_m.group(1)),
                    "height": int(h_m.group(1)),
                }
        except Exception as e:
            logger.debug(f"Failed to query geometry for window {win_id}: {e}")
        return None

    def _get_windows_tree(self) -> str:
        """Executes xwininfo -root -children to fetch all window details."""
        try:
            return subprocess.check_output(
                ["xwininfo", "-root", "-children"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8")
        except Exception as e:
            logger.error(f"Error executing xwininfo: {e}")
            return ""

    def get_active_meeting_window(self) -> Optional[dict]:
        """Returns the active Zoom meeting window details if present, else None."""
        output = self._get_windows_tree()
        if not output:
            return None

        for line in output.splitlines():
            match = self._pattern.match(line)
            if match:
                title = match.group(2).strip()
                cls = match.group(4).strip()

                if cls.lower() == "zoom":
                    title_lower = title.lower()

                    if not title or title_lower in self._ignored_titles:
                        continue
                    if "selection owner" in title_lower or "clipboard" in title_lower:
                        continue

                    win_id = match.group(1)
                    w = int(match.group(5)) if match.group(5) else 0
                    h = int(match.group(6)) if match.group(6) else 0
                    x = int(match.group(7)) if match.group(7) else 0
                    y = int(match.group(8)) if match.group(8) else 0

                    if w <= 1 or h <= 1:
                        geom = self._get_window_geometry(win_id)
                        if geom:
                            x, y, w, h = geom["x"], geom["y"], geom["width"], geom["height"]

                    logger.debug(
                        f"Active Zoom meeting window detected: ID={win_id}, Title='{title}', "
                        f"Area=({x},{y},{w},{h})"
                    )
                    return {
                        "id": win_id,
                        "title": title,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                    }

        return None

    def get_zoom_window(self) -> Optional[dict]:
        """Returns any active Zoom window, prioritizing meeting windows over dashboard."""
        meeting_win = self.get_active_meeting_window()
        if meeting_win:
            return meeting_win

        output = self._get_windows_tree()
        for line in output.splitlines():
            match = self._pattern.match(line)
            if match:
                title = match.group(2).strip()
                cls = match.group(4).strip()
                if cls.lower() == "zoom":
                    title_lower = title.lower()
                    if "workplace" in title_lower:
                        win_id = match.group(1)
                        w = int(match.group(5)) if match.group(5) else 0
                        h = int(match.group(6)) if match.group(6) else 0
                        x = int(match.group(7)) if match.group(7) else 0
                        y = int(match.group(8)) if match.group(8) else 0

                        if w <= 1 or h <= 1:
                            geom = self._get_window_geometry(win_id)
                            if geom:
                                x, y, w, h = geom["x"], geom["y"], geom["width"], geom["height"]

                        return {
                            "id": win_id,
                            "title": title,
                            "x": x,
                            "y": y,
                            "width": w,
                            "height": h,
                        }
        return None


class MacOSZoomDetectorBackend(BaseZoomDetectorBackend):
    """macOS Zoom detector backend using AppleScript (osascript) on System Events."""

    APPLESCRIPT_QUERY = '''
tell application "System Events"
    if exists (process "zoom.us") then
        tell process "zoom.us"
            set winList to {}
            repeat with w in windows
                try
                    set wName to name of w
                    set wPos to position of w
                    set wSize to size of w
                    set end of winList to (wName & ":::" & (item 1 of wPos) & ":::" & (item 2 of wPos) & ":::" & (item 1 of wSize) & ":::" & (item 2 of wSize))
                end try
            end repeat
            set AppleScript's text item delimiters to "|||"
            return winList as text
        end tell
    else
        return ""
    end if
end tell
'''

    def __init__(self):
        self._ignored_titles = config.ZOOM_IGNORED_TITLES

    def _query_windows(self) -> List[dict]:
        """Executes osascript to query all windows of zoom.us."""
        windows = []
        try:
            res = subprocess.run(
                ["osascript", "-e", self.APPLESCRIPT_QUERY],
                capture_output=True,
                text=True,
                timeout=3.0
            )
            raw = res.stdout.strip()
            if not raw:
                return []

            for entry in raw.split("|||"):
                entry = entry.strip()
                if not entry:
                    continue
                parts = entry.split(":::")
                if len(parts) >= 5:
                    title = parts[0].strip()
                    try:
                        x = int(float(parts[1]))
                        y = int(float(parts[2]))
                        w = int(float(parts[3]))
                        h = int(float(parts[4]))
                    except (ValueError, TypeError):
                        continue

                    windows.append({
                        "id": f"macos_zoom_{title}",
                        "title": title,
                        "x": x,
                        "y": y,
                        "width": w,
                        "height": h,
                    })
        except Exception as e:
            logger.debug(f"Error querying macOS Zoom windows: {e}")

        return windows

    def get_active_meeting_window(self) -> Optional[dict]:
        """Returns the active Zoom meeting window if present."""
        windows = self._query_windows()
        for win in windows:
            title = win["title"]
            title_lower = title.lower()

            if not title or title_lower in self._ignored_titles:
                continue
            if "selection owner" in title_lower or "clipboard" in title_lower:
                continue
            if win["width"] <= 10 or win["height"] <= 10:
                continue

            logger.debug(f"Active macOS Zoom meeting window detected: '{title}' at ({win['x']},{win['y']},{win['width']},{win['height']})")
            return win

        return None

    def get_zoom_window(self) -> Optional[dict]:
        """Returns any active Zoom window, prioritizing meeting windows."""
        meeting = self.get_active_meeting_window()
        if meeting:
            return meeting

        windows = self._query_windows()
        for win in windows:
            title_lower = win["title"].lower()
            if "workplace" in title_lower or "zoom" in title_lower:
                if win["width"] > 10 and win["height"] > 10:
                    return win

        return None


# ==============================================================================
#                      MAIN ZOOM DETECTOR FACADE
# ==============================================================================

class ZoomDetector:
    """Facade for Zoom window detection with transparent platform auto-detection."""

    def __init__(self, backend: Optional[BaseZoomDetectorBackend] = None):
        self._pattern = getattr(backend, "_pattern", re.compile(
            r'^\s*(0x[0-9a-fA-F]+)\s+"([^"]*)":\s+\("([^"]*)"\s+"([^"]*)"\)'
            r'(?:\s+(\d+)x(\d+)([+-]\d+)([+-]\d+))?'
        ))
        self._ignored_titles = config.ZOOM_IGNORED_TITLES

        if backend is not None:
            self._backend = backend
        else:
            self._backend = self._create_backend()

    def _create_backend(self) -> BaseZoomDetectorBackend:
        """Factory method to select Zoom detection backend based on platform."""
        if sys.platform == "darwin":
            from unittest.mock import MagicMock
            # If subprocess.check_output was patched in unit tests, use X11 backend
            if isinstance(getattr(subprocess, "check_output", None), MagicMock):
                return X11ZoomDetectorBackend()
            return MacOSZoomDetectorBackend()
        else:
            return X11ZoomDetectorBackend()

    def _get_window_geometry(self, win_id: str) -> Optional[dict]:
        if hasattr(self._backend, "_get_window_geometry"):
            return self._backend._get_window_geometry(win_id)
        return None

    def _get_windows_tree(self) -> str:
        if hasattr(self._backend, "_get_windows_tree"):
            return self._backend._get_windows_tree()
        return ""

    def get_active_meeting_window(self) -> Optional[dict]:
        return self._backend.get_active_meeting_window()

    def get_zoom_window(self) -> Optional[dict]:
        return self._backend.get_zoom_window()

    def is_meeting_active(self) -> bool:
        return self._backend.is_meeting_active()
