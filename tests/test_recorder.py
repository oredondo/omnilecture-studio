import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Ensure the project directory is in the path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import config
from recorder import ZoomDetector, VideoRecorder, MediaProcessor
from recorder.detector import X11ZoomDetectorBackend, MacOSZoomDetectorBackend
from recorder.video_recorder import GnomeScreencastBackend, AVFoundationVideoBackend


# ==============================================================================
# TESTS FOR ZOOMDETECTOR (detector.py)
# ==============================================================================

class TestZoomDetector:
    
    @patch('subprocess.check_output')
    def test_no_windows_active(self, mock_check_output):
        # Mock empty window tree output
        mock_check_output.return_value = b"xwininfo: Window id: 0x4ef (the root window) (has no name)\n  2 children:\n"
        detector = ZoomDetector()
        assert detector.is_meeting_active() is False

    @patch('subprocess.check_output')
    def test_zoom_workplace_only_inactive(self, mock_check_output):
        # Mock output with main dashboard window only
        mock_check_output.return_value = (
            b'     0xc00020 "Zoom Workplace": ("zoom" "zoom")  200x50+860+489  +860+489\n'
            b'     0xc0001d "zoom": ()\n'
        )
        detector = ZoomDetector()
        assert detector.is_meeting_active() is False

    @patch('subprocess.check_output')
    def test_zoom_meeting_detected_active(self, mock_check_output):
        # Mock output containing a meeting window (e.g. "Zoom Meeting" or "Reunion")
        mock_check_output.return_value = (
            b'     0xc00020 "Zoom Workplace": ("zoom" "zoom")  200x50+860+489  +860+489\n'
            b'     0xc00055 "Zoom Meeting": ("zoom" "zoom")  1024x768+100+100  +100+100\n'
        )
        detector = ZoomDetector()
        assert detector.is_meeting_active() is True

    @patch('subprocess.check_output')
    def test_spanish_zoom_meeting_detected_active(self, mock_check_output):
        # Mock output containing Spanish meeting window name
        mock_check_output.return_value = (
            b'     0xc00020 "Zoom Workplace": ("zoom" "zoom")  200x50+860+489  +860+489\n'
            b'     0xc00055 "Reunion de Zoom": ("zoom" "zoom")  1024x768+100+100  +100+100\n'
        )
        detector = ZoomDetector()
        assert detector.is_meeting_active() is True


# ==============================================================================
# TESTS FOR VIDEORECORDER (video_recorder.py)
# ==============================================================================

class TestVideoRecorder:

    @patch('dbus.SessionBus')
    def test_video_recorder_init_success(self, mock_session_bus):
        # Mock DBus objects
        mock_bus_instance = MagicMock()
        mock_session_bus.return_value = mock_bus_instance
        mock_obj = MagicMock()
        mock_bus_instance.get_object.return_value = mock_obj
        
        # Initialize
        recorder = VideoRecorder(filename_template="test_temp_vid")
        
        # Verify dbus connection
        mock_bus_instance.get_object.assert_called_once_with(
            "org.gnome.Shell.Screencast", 
            "/org/gnome/Shell/Screencast"
        )
        assert recorder.filename_template == "test_temp_vid"

    @patch('dbus.SessionBus')
    @patch('dbus.Boolean')
    def test_video_recorder_start_stop(self, mock_dbus_bool, mock_session_bus):
        # Setup DBus mock
        mock_bus_instance = MagicMock()
        mock_session_bus.return_value = mock_bus_instance
        mock_obj = MagicMock()
        mock_bus_instance.get_object.return_value = mock_obj
        
        # Mock Screencast interface methods
        mock_iface = MagicMock()
        mock_iface.Screencast.return_value = (True, "/home/user/Videos/test_temp_vid.webm")
        mock_iface.StopScreencast.return_value = True
        
        with patch('dbus.Interface', return_value=mock_iface):
            recorder = VideoRecorder(filename_template="test_temp_vid")
            
            # Start
            success = recorder.start()
            assert success is True
            assert recorder._is_recording is True
            assert recorder.recorded_file == "/home/user/Videos/test_temp_vid.webm"
            
            # Stop
            file_path = recorder.stop()
            assert file_path == "/home/user/Videos/test_temp_vid.webm"
            assert recorder._is_recording is False
            mock_iface.StopScreencast.assert_called_once()

    @patch('dbus.SessionBus')
    @patch('dbus.Boolean')
    def test_video_recorder_start_with_area(self, mock_dbus_bool, mock_session_bus):
        mock_bus_instance = MagicMock()
        mock_session_bus.return_value = mock_bus_instance
        mock_obj = MagicMock()
        mock_bus_instance.get_object.return_value = mock_obj

        mock_iface = MagicMock()
        mock_iface.ScreencastArea.return_value = (True, "/home/user/Videos/test_area_vid.webm")
        mock_iface.StopScreencast.return_value = True

        with patch('dbus.Interface', return_value=mock_iface):
            recorder = VideoRecorder(filename_template="test_area_vid")
            success = recorder.start(area=(1920, 261, 1920, 1080))
            assert success is True
            assert recorder._is_recording is True
            assert recorder.recorded_file == "/home/user/Videos/test_area_vid.webm"
            mock_iface.ScreencastArea.assert_called_once()
            mock_iface.Screencast.assert_not_called()


# ==============================================================================
# TESTS FOR MEDIAPROCESSOR (processor.py)
# ==============================================================================

class TestMediaProcessor:

    @patch('shutil.which')
    def test_ffmpeg_not_available(self, mock_which):
        # Mock FFmpeg missing
        mock_which.return_value = None
        processor = MediaProcessor()
        
        assert processor.is_available() is False
        assert processor.merge_and_compress("v.webm", "a.ogg", "out.mp4") is False

    @patch('shutil.which')
    @patch('os.path.exists')
    @patch('subprocess.Popen')
    @patch('subprocess.run')
    @patch('os.remove')
    def test_merge_and_compress_success(self, mock_remove, mock_run, mock_popen, mock_exists, mock_which):
        # Mock FFmpeg found and files present
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_exists.return_value = True # video and audio exist
        
        # Mock get_duration (via subprocess.run)
        mock_duration_result = MagicMock()
        mock_duration_result.stdout = "60.0"
        mock_run.return_value = mock_duration_result
        
        # Mock Popen
        mock_process = MagicMock()
        mock_process.stdout.readline.return_value = ""
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        processor = MediaProcessor()
        success = processor.merge_and_compress("v.webm", "a.ogg", "out.mp4")
        
        assert success is True
        
        # Verify FFmpeg execution with config variables
        mock_popen.assert_called_once()
        cmd_arg = mock_popen.call_args[0][0]
        
        assert "/usr/bin/ffmpeg" in cmd_arg
        assert "-crf" in cmd_arg
        assert str(config.VIDEO_CRF) in cmd_arg
        assert config.VIDEO_PRESET in cmd_arg
        assert config.VIDEO_TUNE in cmd_arg
        assert config.AUDIO_BITRATE in cmd_arg
        assert "libmp3lame" in cmd_arg
        assert config.AUDIO_MP3_BITRATE in cmd_arg
        
        # Verify temp files cleanup
        mock_remove.assert_any_call("v.webm")
        mock_remove.assert_any_call("a.ogg")

    @patch('shutil.which')
    @patch('os.path.exists')
    @patch('subprocess.Popen')
    @patch('subprocess.run')
    def test_compress_video_success(self, mock_run, mock_popen, mock_exists, mock_which):
        # Mock FFmpeg found and file present
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_exists.return_value = True

        mock_duration_result = MagicMock()
        mock_duration_result.stdout = "120.0"
        mock_run.return_value = mock_duration_result

        mock_process = MagicMock()
        mock_process.stdout.readline.return_value = ""
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        processor = MediaProcessor()
        success = processor.compress_video("input.mp4", "out.mp4")

        assert success is True
        mock_popen.assert_called_once()
        cmd_arg = mock_popen.call_args[0][0]

        assert "/usr/bin/ffmpeg" in cmd_arg
        assert "-i" in cmd_arg
        assert "input.mp4" in cmd_arg
        assert "-crf" in cmd_arg
        assert str(config.VIDEO_CRF) in cmd_arg
        assert config.VIDEO_PRESET in cmd_arg
        assert "libmp3lame" in cmd_arg
        assert getattr(config, "AUDIO_MP3_BITRATE", "128k") in cmd_arg


# ==============================================================================
# TESTS FOR MACOS ZOOM DETECTOR BACKEND (MacOSZoomDetectorBackend)
# ==============================================================================

class TestMacOSZoomDetectorBackend:

    @patch('subprocess.run')
    def test_macos_zoom_no_windows(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        backend = MacOSZoomDetectorBackend()
        assert backend.is_meeting_active() is False
        assert backend.get_active_meeting_window() is None
        assert backend.get_zoom_window() is None

    @patch('subprocess.run')
    def test_macos_zoom_workplace_only(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Zoom Workplace:::100:::100:::800:::600\n"
        mock_run.return_value = mock_result

        backend = MacOSZoomDetectorBackend()
        assert backend.is_meeting_active() is False
        assert backend.get_active_meeting_window() is None
        zoom_win = backend.get_zoom_window()
        assert zoom_win is not None
        assert zoom_win["title"] == "Zoom Workplace"
        assert zoom_win["width"] == 800

    @patch('subprocess.run')
    def test_macos_zoom_meeting_active(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Zoom Workplace:::0:::0:::600:::400|||Reunión de Zoom:::100:::200:::1280:::720\n"
        mock_run.return_value = mock_result

        backend = MacOSZoomDetectorBackend()
        assert backend.is_meeting_active() is True
        meeting_win = backend.get_active_meeting_window()
        assert meeting_win is not None
        assert meeting_win["title"] == "Reunión de Zoom"
        assert meeting_win["x"] == 100
        assert meeting_win["y"] == 200
        assert meeting_win["width"] == 1280
        assert meeting_win["height"] == 720


# ==============================================================================
# TESTS FOR MACOS VIDEO BACKEND (AVFoundationVideoBackend)
# ==============================================================================

class TestMacOSVideoBackend:

    @patch('subprocess.run')
    def test_discover_screens(self, mock_run):
        mock_result = MagicMock()
        mock_result.stderr = (
            "AVFoundation video devices:\n"
            "[0] FaceTime HD Camera\n"
            "[1] Capture screen 0\n"
            "[2] Capture screen 1\n"
            "AVFoundation audio devices:\n"
            "[0] Built-in Microphone\n"
        )
        mock_run.return_value = mock_result

        backend = AVFoundationVideoBackend(filename_template="test_mac_vid", ffmpeg_path="/usr/bin/ffmpeg")
        screens = backend.discover_screens()
        assert len(screens) == 2
        assert screens[0] == {"index": 1, "name": "Capture screen 0"}
        assert screens[1] == {"index": 2, "name": "Capture screen 1"}

    @patch('subprocess.Popen')
    def test_start_and_stop(self, mock_popen):
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.stdin.closed = False
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        backend = AVFoundationVideoBackend(filename_template="test_mac_vid", ffmpeg_path="/usr/bin/ffmpeg")
        with patch.object(backend, 'discover_screens', return_value=[
            {"index": 1, "name": "Capture screen 0"},
            {"index": 2, "name": "Capture screen 1"},
        ]):
            assert backend.start(draw_cursor=True, area=(0, 0, 1440, 900)) is True
            assert backend.is_recording is True
            assert backend.recorded_file is not None

            # Verify FFmpeg command
            cmd = mock_popen.call_args[0][0]
            assert "/usr/bin/ffmpeg" in cmd
            assert "-f" in cmd
            assert "avfoundation" in cmd
            assert "1:none" in cmd
            assert "-vf" in cmd
            assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in cmd

            # Stop
            out_file = backend.stop()
            assert out_file == backend.recorded_file
            assert backend.is_recording is False
            mock_process.stdin.write.assert_called_with(b"q\n")
            mock_process.wait.assert_called_once()


# ==============================================================================
# TESTS FOR PLATFORM AUTODETECTION (Factory / Facade)
# ==============================================================================

class TestPlatformAutoDetection:

    def test_zoom_detector_autodetection_linux(self):
        with patch('sys.platform', 'linux'):
            detector = ZoomDetector()
            assert isinstance(detector._backend, X11ZoomDetectorBackend)

    def test_zoom_detector_autodetection_macos(self):
        with patch('sys.platform', 'darwin'):
            detector = ZoomDetector()
            assert isinstance(detector._backend, MacOSZoomDetectorBackend)

    @patch('dbus.SessionBus')
    @patch('dbus.Interface')
    def test_video_recorder_autodetection_linux(self, mock_iface, mock_bus):
        with patch('sys.platform', 'linux'):
            recorder = VideoRecorder(filename_template="test_linux")
            assert isinstance(recorder._backend, GnomeScreencastBackend)

    def test_video_recorder_autodetection_macos(self):
        with patch('sys.platform', 'darwin'):
            # When dbus is not patched as MagicMock in backend creation
            with patch('shutil.which', return_value="/usr/bin/ffmpeg"):
                recorder = VideoRecorder(filename_template="test_mac", backend=AVFoundationVideoBackend("test_mac", ffmpeg_path="/usr/bin/ffmpeg"))
                assert isinstance(recorder._backend, AVFoundationVideoBackend)

