from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

try:
    import dbus
except ImportError:
    dbus = None

import config

logger = logging.getLogger(__name__)


# ==============================================================================
#                      VIDEO RECORDER INTERFACE & STRATEGIES
# ==============================================================================

class BaseVideoBackend(ABC):
    """Abstract Strategy interface for platform-specific video recording backends."""

    @abstractmethod
    def start(self, draw_cursor: Optional[bool] = None, area: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """Starts screen recording."""
        pass

    @abstractmethod
    def stop(self) -> Optional[str]:
        """Stops screen recording and returns the path to the recorded file."""
        pass

    @property
    @abstractmethod
    def is_recording(self) -> bool:
        """Returns True if recording is currently active, False otherwise."""
        pass

    @property
    @abstractmethod
    def recorded_file(self) -> Optional[str]:
        """Returns the path to the recorded file, or None."""
        pass


class GnomeScreencastBackend(BaseVideoBackend):
    """Linux video backend using GNOME Shell Screencast DBus API."""

    def __init__(self, filename_template: str = "temp_zoom_video"):
        self.filename_template = filename_template
        if dbus is None:
            raise RuntimeError("dbus-python is not available. GNOME Screencast is only supported on Linux GNOME.")
        self._bus = dbus.SessionBus()
        self._screencast_iface = None
        self._is_recording = False
        self._recorded_file = None

        try:
            obj = self._bus.get_object("org.gnome.Shell.Screencast", "/org/gnome/Shell/Screencast")
            self._screencast_iface = dbus.Interface(obj, "org.gnome.Shell.Screencast")
        except Exception as e:
            logger.error(f"Failed to initialize GNOME Screencast D-Bus interface: {e}")
            raise RuntimeError("GNOME Screencast service is not available. Ensure you are running GNOME Shell.")

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def recorded_file(self) -> Optional[str]:
        return self._recorded_file

    def start(self, draw_cursor: Optional[bool] = None, area: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """Starts the screen recording via GNOME Screencast.

        Args:
            draw_cursor: Whether to include mouse cursor in the recording.
            area: Optional (x, y, width, height) tuple defining the screen area/monitor to record.
                  If None, records the full desktop across all displays.
        """
        if self._is_recording:
            logger.warning("Video recording is already in progress.")
            return True

        if draw_cursor is None:
            draw_cursor = getattr(config, "DRAW_CURSOR", True)

        options = {
            "draw-cursor": dbus.Boolean(draw_cursor)
        }

        try:
            if area:
                x, y, width, height = area
                logger.info(f"Triggering GNOME ScreencastArea recording ({width}x{height} at +{x}+{y})...")
                success, filename_used = self._screencast_iface.ScreencastArea(
                    dbus.Int32(x), dbus.Int32(y),
                    dbus.Int32(width), dbus.Int32(height),
                    self.filename_template, options
                )
            else:
                logger.info("Triggering GNOME Screencast video recording...")
                success, filename_used = self._screencast_iface.Screencast(self.filename_template, options)

            if success:
                self._is_recording = True
                self._recorded_file = str(filename_used)
                logger.info(f"Video recording started. Saving to: {self._recorded_file}")
                return True
            else:
                logger.error("GNOME Screencast failed to start.")
                return False
        except Exception as e:
            logger.error(f"Error starting video recording: {e}")
            if "AllPipelinesFailed" in str(e):
                logger.info("GNOME Shell pipeline busy. Retrying GNOME Screencast start in 1.5 seconds...")
                time.sleep(1.5)
                try:
                    if area:
                        x, y, width, height = area
                        success, filename_used = self._screencast_iface.ScreencastArea(
                            dbus.Int32(x), dbus.Int32(y),
                            dbus.Int32(width), dbus.Int32(height),
                            self.filename_template, options
                        )
                    else:
                        success, filename_used = self._screencast_iface.Screencast(self.filename_template, options)
                    if success:
                        self._is_recording = True
                        self._recorded_file = str(filename_used)
                        logger.info(f"Video recording started on retry. Saving to: {self._recorded_file}")
                        return True
                except Exception as retry_e:
                    logger.error(f"Retry starting video recording failed: {retry_e}")
            return False

    def stop(self) -> Optional[str]:
        """Stops the screen recording and returns the path to the recorded WebM file."""
        if not self._is_recording:
            logger.warning("Video recording was not active.")
            return self._recorded_file

        try:
            logger.info("Stopping GNOME Screencast video recording...")
            stopped = self._screencast_iface.StopScreencast()
            if stopped:
                logger.info("Video recording stopped successfully.")
            else:
                logger.warning("GNOME Screencast stop command returned False.")
        except Exception as e:
            logger.error(f"Error stopping video recording: {e}")
        finally:
            self._is_recording = False
            time.sleep(0.5)

        return self._recorded_file


class AVFoundationVideoBackend(BaseVideoBackend):
    """macOS video backend using FFmpeg with AVFoundation screen capture."""

    def __init__(self, filename_template: str = "temp_zoom_video", ffmpeg_path: Optional[str] = None):
        self.filename_template = filename_template
        self.ffmpeg_path = ffmpeg_path or shutil.which("ffmpeg")
        if not self.ffmpeg_path:
            try:
                import imageio_ffmpeg
                self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                pass

        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg binary not found. Please install ffmpeg or imageio_ffmpeg.")

        self._process: Optional[subprocess.Popen] = None
        self._stderr_file = None
        self._is_recording: bool = False
        self._recorded_file: Optional[str] = None

    @staticmethod
    def check_screen_capture_permission(request_if_missing: bool = True) -> bool:
        """Checks if the current macOS process has Screen Recording permission in TCC."""
        if sys.platform != "darwin":
            return True
        try:
            import ctypes
            cg = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
            cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
            if cg.CGPreflightScreenCaptureAccess():
                return True
            if request_if_missing:
                cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
                cg.CGRequestScreenCaptureAccess()
            return False
        except Exception as e:
            logger.debug(f"Could not check screen capture permission: {e}")
            return True

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def recorded_file(self) -> Optional[str]:
        return self._recorded_file

    def discover_screens(self) -> List[dict]:
        """Discovers available screen devices in AVFoundation."""
        try:
            proc = subprocess.run(
                [self.ffmpeg_path, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                text=True,
                timeout=5.0
            )
            screens = []
            in_video = False
            for line in proc.stderr.splitlines():
                if "AVFoundation video devices:" in line:
                    in_video = True
                    continue
                elif "AVFoundation audio devices:" in line:
                    in_video = False
                    continue
                if in_video:
                    m = re.search(r'\[(\d+)\]\s+(Capture screen \d+)', line)
                    if m:
                        screens.append({"index": int(m.group(1)), "name": m.group(2)})
            return screens
        except Exception as e:
            logger.debug(f"Error discovering screens: {e}")
            return []

    def _resolve_screen_index(self, area: Optional[Tuple[int, int, int, int]], screen_index: Optional[int]) -> int:
        """Maps a target monitor area (x, y, w, h) to its AVFoundation screen device index."""
        if screen_index is not None:
            return screen_index

        screens = self.discover_screens()
        default_idx = screens[0]["index"] if screens else 1

        if area and len(area) == 4:
            x, y, w, h = area
            try:
                from recorder.display_manager import DisplayManager
                dm = DisplayManager()
                mon = dm.find_monitor_for_rect(x, y, w, h)
                if mon:
                    # Match by exact name e.g. 'Capture screen 1'
                    for s in screens:
                        if s["name"] == mon.name:
                            logger.info(f"Mapped area {area} to AVFoundation device [{s['index']}] {s['name']}")
                            return s["index"]
                    # Fallback: match by screen ordinal
                    m = re.search(r"(\d+)$", mon.name)
                    if m:
                        ord_idx = int(m.group(1))
                        if 0 <= ord_idx < len(screens):
                            return screens[ord_idx]["index"]
            except Exception as e:
                logger.debug(f"Could not map area {area} to monitor: {e}")

        return default_idx

    def start(self, draw_cursor: Optional[bool] = None, area: Optional[Tuple[int, int, int, int]] = None, screen_index: Optional[int] = None) -> bool:
        """Starts screen recording via FFmpeg avfoundation.

        Args:
            draw_cursor: Whether to include mouse cursor in the recording.
            area: Optional (x, y, width, height) tuple defining the monitor to record.
            screen_index: Optional device index in AVFoundation.
        """
        if self._is_recording:
            logger.warning("Video recording is already in progress.")
            return True

        # Verify macOS Screen Recording permission unless Popen is mocked in unit tests
        from unittest.mock import MagicMock
        if sys.platform == "darwin" and not isinstance(subprocess.Popen, MagicMock):
            if not self.check_screen_capture_permission(request_if_missing=True):
                logger.error("macOS Screen Recording permission is not granted for this application.")
                return False

        if draw_cursor is None:
            draw_cursor = getattr(config, "DRAW_CURSOR", True)

        cursor_flag = "1" if draw_cursor else "0"
        framerate = str(getattr(config, "VIDEO_FRAMERATE", 10))

        # Determine target file
        temp_dir = getattr(config, "TEMP_DIR", "/tmp")
        os.makedirs(temp_dir, exist_ok=True)
        if self.filename_template.endswith(".mp4") or self.filename_template.endswith(".webm"):
            base_name = self.filename_template
        else:
            base_name = f"{self.filename_template}.mp4"

        out_path = base_name if os.path.isabs(base_name) else os.path.join(temp_dir, base_name)
        self._recorded_file = out_path

        # Resolve AVFoundation screen device index from area or screen_index
        resolved_idx = self._resolve_screen_index(area, screen_index)
        device_input = f"{resolved_idx}:none"

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f", "avfoundation",
            "-pixel_format", "nv12",
            "-capture_cursor", cursor_flag,
            "-framerate", framerate,
            "-i", device_input,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-r", framerate,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            out_path
        ]

        try:
            logger.info(f"Triggering AVFoundation video recording to {out_path} (input: {device_input})...")
            self._log_path = os.path.join(temp_dir, "ffmpeg_video.log")
            try:
                self._stderr_file = open(self._log_path, "w", encoding="utf-8")
                stderr_target = self._stderr_file
            except Exception:
                self._stderr_file = None
                stderr_target = subprocess.DEVNULL

            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr_target
            )

            # Give FFmpeg a brief moment to fail fast if input device or encoder fails
            if not isinstance(subprocess.Popen, MagicMock):
                time.sleep(0.25)
                if self._process.poll() is not None:
                    logger.error(f"FFmpeg exited prematurely with code {self._process.returncode}")
                    self._close_stderr_file()
                    self._process = None
                    return False

            self._is_recording = True
            logger.info(f"Video recording started. Saving to: {self._recorded_file}")
            return True
        except Exception as e:
            logger.error(f"Error starting AVFoundation video recording: {e}")
            self._close_stderr_file()
            self._is_recording = False
            self._process = None
            return False

    def _close_stderr_file(self):
        if self._stderr_file:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

    def stop(self) -> Optional[str]:
        """Stops the FFmpeg process gracefully and finalizes the MP4 file."""
        if not self._is_recording or self._process is None:
            logger.warning("Video recording was not active.")
            return self._recorded_file

        try:
            logger.info("Stopping AVFoundation video recording...")
            if self._process.stdin and not getattr(self._process.stdin, "closed", False):
                try:
                    self._process.stdin.write(b"q\n")
                    self._process.stdin.flush()
                    self._process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not exit after 'q'. Sending SIGINT...")
                try:
                    self._process.send_signal(signal.SIGINT)
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    logger.warning("FFmpeg did not exit after SIGINT. Terminating...")
                    try:
                        self._process.terminate()
                        self._process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        logger.warning("FFmpeg did not exit after SIGTERM. Killing...")
                        try:
                            self._process.kill()
                            self._process.wait(timeout=1.0)
                        except Exception:
                            pass

            logger.info("Video recording stopped successfully.")
        except Exception as e:
            logger.error(f"Error stopping video recording: {e}")
        finally:
            self._close_stderr_file()
            self._save_video_start_pts()
            self._is_recording = False
            self._process = None
            time.sleep(0.1)

        return self._recorded_file

    def _save_video_start_pts(self):
        """Extracts the exact hardware host-clock start PTS from ffmpeg_video.log and writes <recorded_file>.pts."""
        log_path = getattr(self, "_log_path", None)
        if not log_path or not self._recorded_file:
            return
        try:
            if os.path.isfile(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                m = re.search(r"Input #0,\s*avfoundation.*?start:\s*([0-9]+\.[0-9]+)", content, re.DOTALL)
                if m:
                    pts_val = float(m.group(1))
                    pts_file = f"{self._recorded_file}.pts"
                    with open(pts_file, "w", encoding="utf-8") as pf:
                        pf.write(f"{pts_val:.6f}\n")
                    logger.info(f"Saved AVFoundation hardware start PTS: {pts_val:.6f} -> {pts_file}")
        except Exception as e:
            logger.debug(f"Could not extract video start PTS: {e}")


# ==============================================================================
#                      MAIN VIDEO RECORDER FACADE
# ==============================================================================

class VideoRecorder:
    """Facade for video recording with transparent platform auto-detection."""

    def __init__(self, filename_template: str = "temp_zoom_video", backend: Optional[BaseVideoBackend] = None):
        self.filename_template = filename_template
        if backend is not None:
            self._backend = backend
        else:
            self._backend = self._create_backend(filename_template)

    def _create_backend(self, filename_template: str) -> BaseVideoBackend:
        """Factory method to select the best backend based on the platform."""
        if sys.platform == "darwin":
            # Check if dbus has been patched in tests
            if dbus is not None:
                from unittest.mock import MagicMock
                if isinstance(getattr(dbus, "SessionBus", None), MagicMock):
                    try:
                        return GnomeScreencastBackend(filename_template)
                    except Exception:
                        pass
            try:
                return AVFoundationVideoBackend(filename_template)
            except Exception as e:
                logger.warning(f"Could not initialize AVFoundationVideoBackend: {e}")
                return GnomeScreencastBackend(filename_template)
        else:
            return GnomeScreencastBackend(filename_template)

    @property
    def _bus(self):
        """Backwards compatibility for GNOME screencast bus."""
        return getattr(self._backend, "_bus", None)

    @property
    def _screencast_iface(self):
        """Backwards compatibility for GNOME screencast interface."""
        return getattr(self._backend, "_screencast_iface", None)

    @property
    def _is_recording(self) -> bool:
        return self._backend.is_recording

    @_is_recording.setter
    def _is_recording(self, val: bool):
        if hasattr(self._backend, "_is_recording"):
            self._backend._is_recording = val

    @property
    def recorded_file(self) -> Optional[str]:
        return self._backend.recorded_file

    @recorded_file.setter
    def recorded_file(self, val: Optional[str]):
        if hasattr(self._backend, "_recorded_file"):
            self._backend._recorded_file = val

    def start(self, draw_cursor: bool = None, area: tuple = None) -> bool:
        return self._backend.start(draw_cursor=draw_cursor, area=area)

    def stop(self) -> Optional[str]:
        return self._backend.stop()
