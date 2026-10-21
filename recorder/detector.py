import logging
import re
import subprocess
from typing import Optional

import config

logger = logging.getLogger(__name__)


class ZoomDetector:
    """Detects active Zoom calls and inspects Zoom window geometry."""

    def __init__(self):
        # Pattern to match: id "title": ("instance" "class") [geometry]
        self._pattern = re.compile(
            r'^\s*(0x[0-9a-fA-F]+)\s+"([^"]*)":\s+\("([^"]*)"\s+"([^"]*)"\)'
            r'(?:\s+(\d+)x(\d+)([+-]\d+)([+-]\d+))?'
        )
        # Titles to ignore (main client window and system placeholders) from config
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

                # Check if this window belongs to Zoom
                if cls.lower() == "zoom":
                    title_lower = title.lower()

                    # If title is empty, or belongs to the main dashboard or a service window, skip it
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

    def is_meeting_active(self) -> bool:
        """Returns True if an active Zoom meeting is detected, False otherwise."""
        return self.get_active_meeting_window() is not None
