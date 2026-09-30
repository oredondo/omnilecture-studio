"""
Display and monitor manager for multi-monitor setups on Linux/GNOME Wayland.
Detects connected monitors and maps window coordinates to corresponding displays.
"""

from dataclasses import dataclass
import logging
import re
import subprocess
from typing import List, Optional, Tuple
import dbus

import config

logger = logging.getLogger(__name__)


@dataclass
class Monitor:
    """Represents a display monitor and its geometric boundaries."""
    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool = False

    @property
    def area(self) -> Tuple[int, int, int, int]:
        """Returns the (x, y, width, height) bounding box of the monitor."""
        return (self.x, self.y, self.width, self.height)


class DisplayManager:
    """Detects connected monitors and determines target recording areas."""

    def __init__(self, bus: Optional[dbus.SessionBus] = None):
        self._bus = bus

    def _get_bus(self) -> dbus.SessionBus:
        if self._bus is None:
            self._bus = dbus.SessionBus()
        return self._bus

    def get_monitors(self) -> List[Monitor]:
        """Returns a list of all currently active monitors."""
        monitors = self._get_monitors_from_mutter()
        if not monitors:
            monitors = self._get_monitors_from_xrandr()
        return monitors

    def _get_monitors_from_mutter(self) -> List[Monitor]:
        """Queries monitors via GNOME Mutter DisplayConfig D-Bus interface."""
        monitors: List[Monitor] = []
        try:
            bus = self._get_bus()
            obj = bus.get_object("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig")
            iface = dbus.Interface(obj, "org.gnome.Mutter.DisplayConfig")
            _, monitor_modes, logical_monitors, _ = iface.GetCurrentState()

            current_modes = {}
            for mm in monitor_modes:
                mon_name = str(mm[0][0])
                for mode in mm[1]:
                    mode_props = mode[6] if len(mode) > 6 else {}
                    if mode_props.get("is-current", False):
                        current_modes[mon_name] = (int(mode[1]), int(mode[2]))
                        break

            for lm in logical_monitors:
                x = int(lm[0])
                y = int(lm[1])
                is_primary = bool(lm[4])
                mon_info = lm[5]
                mon_name = str(mon_info[0][0]) if mon_info else "unknown"
                w, h = current_modes.get(mon_name, (1920, 1080))
                monitors.append(Monitor(
                    name=mon_name,
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    is_primary=is_primary
                ))
        except Exception as e:
            logger.debug(f"Failed to query Mutter DisplayConfig: {e}")
        return monitors

    def _get_monitors_from_xrandr(self) -> List[Monitor]:
        """Queries monitors via xrandr --listmonitors command."""
        monitors: List[Monitor] = []
        try:
            output = subprocess.check_output(
                ["xrandr", "--listmonitors"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8")

            # Pattern: 0: +*eDP-1 1920/310x1080/170+1920+261  eDP-1
            pattern = re.compile(
                r'(\d+):\s+\+?(\*?)(\S+)\s+(\d+)(?:/\d+)?x(\d+)(?:/\d+)?\+(\d+)\+(\d+)'
            )
            for line in output.splitlines():
                match = pattern.search(line)
                if match:
                    is_primary = bool(match.group(2))
                    name = match.group(3)
                    w = int(match.group(4))
                    h = int(match.group(5))
                    x = int(match.group(6))
                    y = int(match.group(7))
                    monitors.append(Monitor(
                        name=name,
                        x=x,
                        y=y,
                        width=w,
                        height=h,
                        is_primary=is_primary
                    ))
        except Exception as e:
            logger.debug(f"Failed to query xrandr: {e}")
        return monitors

    def get_primary_monitor(self) -> Optional[Monitor]:
        """Returns the primary monitor or the first available monitor."""
        monitors = self.get_monitors()
        if not monitors:
            return None
        for m in monitors:
            if m.is_primary:
                return m
        return monitors[0]

    def find_monitor_for_rect(self, x: int, y: int, width: int, height: int) -> Optional[Monitor]:
        """Finds which monitor contains or best overlaps the specified rectangle."""
        monitors = self.get_monitors()
        if not monitors:
            return None

        # Calculate center point
        center_x = x + width // 2
        center_y = y + height // 2

        # Check if center falls strictly inside any monitor
        for m in monitors:
            if m.x <= center_x < m.x + m.width and m.y <= center_y < m.y + m.height:
                return m

        # Check best intersection area if center doesn't match
        best_monitor = None
        best_area = 0
        for m in monitors:
            dx = min(x + width, m.x + m.width) - max(x, m.x)
            dy = min(y + height, m.y + m.height) - max(y, m.y)
            if dx > 0 and dy > 0:
                area = dx * dy
                if area > best_area:
                    best_area = area
                    best_monitor = m

        if best_monitor:
            return best_monitor

        # Fallback to primary monitor
        return self.get_primary_monitor()

    def get_target_monitor(self, detector, target_mode: Optional[str] = None) -> Optional[Monitor]:
        """Determines which monitor should be recorded based on configuration and Zoom window."""
        if target_mode is None:
            target_mode = getattr(config, "RECORD_TARGET", "zoom_monitor")

        if target_mode == "all_monitors":
            return None

        if target_mode == "zoom_monitor" and detector:
            zoom_win = detector.get_zoom_window()
            if zoom_win and zoom_win.get("width", 0) > 0 and zoom_win.get("height", 0) > 0:
                mon = self.find_monitor_for_rect(
                    zoom_win["x"], zoom_win["y"], zoom_win["width"], zoom_win["height"]
                )
                if mon:
                    logger.info(
                        f"Targeting monitor '{mon.name}' ({mon.width}x{mon.height}+{mon.x}+{mon.y}) "
                        f"where Zoom window '{zoom_win.get('title')}' is active."
                    )
                    return mon

        return self.get_primary_monitor()

    def get_target_area(self, detector, target_mode: Optional[str] = None) -> Optional[Tuple[int, int, int, int]]:
        """Returns the (x, y, width, height) tuple to record, or None for full desktop."""
        target_mode = target_mode or getattr(config, "RECORD_TARGET", "zoom_monitor")
        if target_mode == "all_monitors":
            return None

        mon = self.get_target_monitor(detector, target_mode)
        return mon.area if mon else None
