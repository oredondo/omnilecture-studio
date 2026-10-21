import logging
import time
import dbus

import config

logger = logging.getLogger(__name__)


class VideoRecorder:
    """Manages full-screen or monitor-targeted video recording via GNOME Shell Screencast DBus API."""

    def __init__(self, filename_template: str = "temp_zoom_video"):
        self.filename_template = filename_template
        self._bus = dbus.SessionBus()
        self._screencast_iface = None
        self._is_recording = False
        self.recorded_file = None

        try:
            obj = self._bus.get_object("org.gnome.Shell.Screencast", "/org/gnome/Shell/Screencast")
            self._screencast_iface = dbus.Interface(obj, "org.gnome.Shell.Screencast")
        except Exception as e:
            logger.error(f"Failed to initialize GNOME Screencast D-Bus interface: {e}")
            raise RuntimeError("GNOME Screencast service is not available. Ensure you are running GNOME Shell.")

    def start(self, draw_cursor: bool = None, area: tuple = None) -> bool:
        """Starts the screen recording.

        Args:
            draw_cursor: Whether to include mouse cursor in the recording.
            area: Optional (x, y, width, height) tuple defining the screen area/monitor to record.
                  If None, records the full desktop across all displays.
        """
        if self._is_recording:
            logger.warning("Video recording is already in progress.")
            return True

        if draw_cursor is None:
            draw_cursor = config.DRAW_CURSOR

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
                self.recorded_file = str(filename_used)
                logger.info(f"Video recording started. Saving to: {self.recorded_file}")
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
                        self.recorded_file = str(filename_used)
                        logger.info(f"Video recording started on retry. Saving to: {self.recorded_file}")
                        return True
                except Exception as retry_e:
                    logger.error(f"Retry starting video recording failed: {retry_e}")
            return False

    def stop(self) -> str:
        """Stops the screen recording and returns the path to the recorded WebM file."""
        if not self._is_recording:
            logger.warning("Video recording was not active.")
            return self.recorded_file

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

        return self.recorded_file
