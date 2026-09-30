import os
import sys
from unittest.mock import MagicMock, patch

# Ensure the project directory is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from detector import ZoomDetector  # noqa: E402
from display_manager import DisplayManager, Monitor  # noqa: E402


class TestDisplayManager:

    @patch('subprocess.check_output')
    def test_xrandr_monitors_parsing(self, mock_check_output):
        mock_check_output.return_value = (
            b"Monitors: 2\n"
            b" 0: +*eDP-1 1920/310x1080/170+1920+261  eDP-1\n"
            b" 1: +HDMI-1 1920/600x1080/340+0+0  HDMI-1\n"
        )
        dm = DisplayManager()
        monitors = dm._get_monitors_from_xrandr()

        assert len(monitors) == 2
        assert monitors[0].name == "eDP-1"
        assert monitors[0].is_primary is True
        assert monitors[0].x == 1920
        assert monitors[0].y == 261
        assert monitors[0].width == 1920
        assert monitors[0].height == 1080

        assert monitors[1].name == "HDMI-1"
        assert monitors[1].is_primary is False
        assert monitors[1].x == 0
        assert monitors[1].y == 0
        assert monitors[1].width == 1920
        assert monitors[1].height == 1080

    def test_find_monitor_for_rect(self):
        dm = DisplayManager()
        m1 = Monitor(name="HDMI-1", x=0, y=0, width=1920, height=1080, is_primary=False)
        m2 = Monitor(name="eDP-1", x=1920, y=261, width=1920, height=1080, is_primary=True)

        with patch.object(dm, 'get_monitors', return_value=[m1, m2]):
            # Rect strictly on HDMI-1
            mon = dm.find_monitor_for_rect(x=100, y=100, width=800, height=600)
            assert mon.name == "HDMI-1"

            # Rect strictly on eDP-1
            mon = dm.find_monitor_for_rect(x=2000, y=300, width=1024, height=768)
            assert mon.name == "eDP-1"

            # Rect overlapping mostly on eDP-1
            mon = dm.find_monitor_for_rect(x=1800, y=300, width=1000, height=700)
            assert mon.name == "eDP-1"

    def test_get_target_monitor_zoom_mode(self):
        dm = DisplayManager()
        m1 = Monitor(name="HDMI-1", x=0, y=0, width=1920, height=1080, is_primary=False)
        m2 = Monitor(name="eDP-1", x=1920, y=261, width=1920, height=1080, is_primary=True)

        mock_detector = MagicMock()
        # Zoom meeting is located on HDMI-1
        mock_detector.get_zoom_window.return_value = {
            "id": "0x123",
            "title": "Zoom Meeting",
            "x": 200,
            "y": 150,
            "width": 1280,
            "height": 720
        }

        with patch.object(dm, 'get_monitors', return_value=[m1, m2]):
            target = dm.get_target_monitor(mock_detector, target_mode="zoom_monitor")
            assert target.name == "HDMI-1"
            assert dm.get_target_area(mock_detector, target_mode="zoom_monitor") == (0, 0, 1920, 1080)

    def test_get_target_monitor_all_monitors_mode(self):
        dm = DisplayManager()
        mock_detector = MagicMock()
        assert dm.get_target_monitor(mock_detector, target_mode="all_monitors") is None
        assert dm.get_target_area(mock_detector, target_mode="all_monitors") is None

    def test_get_target_monitor_fallback_primary(self):
        dm = DisplayManager()
        m1 = Monitor(name="HDMI-1", x=0, y=0, width=1920, height=1080, is_primary=False)
        m2 = Monitor(name="eDP-1", x=1920, y=261, width=1920, height=1080, is_primary=True)

        mock_detector = MagicMock()
        # No Zoom window found
        mock_detector.get_zoom_window.return_value = None

        with patch.object(dm, 'get_monitors', return_value=[m1, m2]):
            target = dm.get_target_monitor(mock_detector, target_mode="zoom_monitor")
            assert target.name == "eDP-1"
            assert target.is_primary is True


class TestZoomDetectorGeometry:

    @patch('subprocess.check_output')
    def test_get_active_meeting_window_with_geometry(self, mock_check_output):
        mock_check_output.return_value = (
            b'     0xc00020 "Zoom Workplace": ("zoom" "zoom")  200x50+860+489  +860+489\n'
            b'     0xc00055 "Zoom Meeting": ("zoom" "zoom")  1920x1080+1920+261  +1920+261\n'
        )
        detector = ZoomDetector()
        meeting_win = detector.get_active_meeting_window()

        assert meeting_win is not None
        assert meeting_win["id"] == "0xc00055"
        assert meeting_win["title"] == "Zoom Meeting"
        assert meeting_win["x"] == 1920
        assert meeting_win["y"] == 261
        assert meeting_win["width"] == 1920
        assert meeting_win["height"] == 1080
        assert detector.is_meeting_active() is True

    @patch('subprocess.check_output')
    def test_get_zoom_window_fallback_to_workplace(self, mock_check_output):
        mock_check_output.return_value = (
            b'     0xc00020 "Zoom Workplace": ("zoom" "zoom")  1485x1000+218+40  +218+40\n'
        )
        detector = ZoomDetector()
        assert detector.is_meeting_active() is False

        zoom_win = detector.get_zoom_window()
        assert zoom_win is not None
        assert zoom_win["id"] == "0xc00020"
        assert zoom_win["x"] == 218
        assert zoom_win["y"] == 40
        assert zoom_win["width"] == 1485
        assert zoom_win["height"] == 1000
