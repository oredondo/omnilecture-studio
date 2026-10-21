import os
import sys
from unittest.mock import MagicMock

# Ensure project root is in sys.path
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# Dummy base classes for GTK widgets when PyGObject is not available (e.g. macOS / CI)
class _DummyGtkWidget:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return MagicMock()


class _DummyGtkBox(_DummyGtkWidget):
    pass


class _DummyGtkWindow(_DummyGtkWidget):
    pass


class _DummyGtkDialog(_DummyGtkWidget):
    pass


# Shim PyGObject 'gi' if running on a system without it
if 'gi' not in sys.modules:
    try:
        import gi
    except ImportError:
        mock_gi = MagicMock()

        class PyGIWarning(Warning):
            pass

        mock_gi.PyGIWarning = PyGIWarning
        mock_gi.repository.Gtk.Box = _DummyGtkBox
        mock_gi.repository.Gtk.Window = _DummyGtkWindow
        mock_gi.repository.Gtk.Dialog = _DummyGtkDialog
        mock_gi.repository.Gtk.Orientation.VERTICAL = 1
        mock_gi.repository.Gtk.Orientation.HORIZONTAL = 0

        sys.modules['gi'] = mock_gi
        sys.modules['gi.repository'] = mock_gi.repository
        sys.modules['gi.repository.Gst'] = mock_gi.repository.Gst
        sys.modules['gi.repository.GLib'] = mock_gi.repository.GLib
        sys.modules['gi.repository.Gtk'] = mock_gi.repository.Gtk
        sys.modules['gi.repository.Pango'] = mock_gi.repository.Pango

# Shim dbus if running on a system without it (e.g. macOS)
if 'dbus' not in sys.modules:
    try:
        import dbus
    except ImportError:
        sys.modules['dbus'] = MagicMock()

# Shim cv2 if running in environment without opencv
if 'cv2' not in sys.modules:
    try:
        import cv2
    except ImportError:
        mock_cv2 = MagicMock()
        mock_cv2.COLOR_BGR2RGB = 4
        mock_cv2.COLOR_BGR2GRAY = 6
        mock_cv2.cvtColor.side_effect = lambda img, *args, **kwargs: img
        sys.modules['cv2'] = mock_cv2

# Shim pytesseract if running in environment without pytesseract
if 'pytesseract' not in sys.modules:
    try:
        import pytesseract
    except ImportError:
        sys.modules['pytesseract'] = MagicMock()
