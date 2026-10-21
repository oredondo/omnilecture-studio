import sys
from unittest.mock import MagicMock

# Shim PyGObject 'gi' if running on a system without it (e.g. macOS)
if 'gi' not in sys.modules:
    try:
        import gi
    except ImportError:
        mock_gi = MagicMock()
        class PyGIWarning(Warning):
            pass
        mock_gi.PyGIWarning = PyGIWarning
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
