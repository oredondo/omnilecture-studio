import os
import sys
from unittest.mock import MagicMock, patch

import gi
try:
    gi.require_version('Gtk', '3.0')
except ValueError:
    pass

# Ensure the project directory is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


class TestGUIComponentsImports:
    """Test suite ensuring GUI components and modular tabs initialize properly."""

    @patch('gi.repository.Gtk.Window')
    def test_gui_components_structure(self, mock_window):
        from gui_components.dialogs import DialogUtils
        from gui_components.recorder_tab import RecorderTab
        from gui_components.eir_notes_tab import EIRNotesTab
        from gui_components.handwritten_tab import HandwrittenTab
        from gui_components.dictation_tab import DictationTab

        assert hasattr(DialogUtils, "show_info")
        assert hasattr(DialogUtils, "show_error")
        assert hasattr(DialogUtils, "ask_confirmation")
        assert hasattr(RecorderTab, "on_record_clicked")
        assert hasattr(EIRNotesTab, "on_video_file_set")
        assert hasattr(HandwrittenTab, "on_select_images_clicked")
        assert hasattr(DictationTab, "on_rec_clicked")
        assert hasattr(DictationTab, "on_stop_clicked")
        assert hasattr(DictationTab, "set_remote_whisper")
        assert hasattr(EIRNotesTab, "set_remote_whisper")

    @patch('gi.repository.Gtk.Window')
    def test_main_gui_class(self, mock_window):
        with patch('gui_components.recorder_tab.RecorderTab'), \
             patch('gui_components.eir_notes_tab.EIRNotesTab'), \
             patch('gui_components.handwritten_tab.HandwrittenTab'), \
             patch('gui_components.dictation_tab.DictationTab'):
            from gui import ZoomRecorderGUI
            app = ZoomRecorderGUI()
            assert app is not None
            assert hasattr(app, "btn_whisper_toggle")
            assert hasattr(app, "set_use_remote_whisper")

    def test_whisper_toggle_synchronization(self):
        from gui_components.eir_notes_tab import EIRNotesTab
        from gui_components.dictation_tab import DictationTab

        parent = MagicMock()

        # Test EIRNotesTab sync
        eir = EIRNotesTab.__new__(EIRNotesTab)
        eir.parent_window = parent
        eir.chk_remote_whisper = MagicMock()

        eir.set_remote_whisper(False)
        eir.chk_remote_whisper.set_active.assert_called_with(False)

        widget = MagicMock()
        widget.get_active.return_value = False
        eir.on_whisper_mode_toggled(widget)
        parent.set_use_remote_whisper.assert_called_with(False, source=eir)

        # Test DictationTab sync
        dict_tab = DictationTab.__new__(DictationTab)
        dict_tab.parent_window = parent
        dict_tab.chk_remote_whisper = MagicMock()

        dict_tab.set_remote_whisper(True)
        dict_tab.chk_remote_whisper.set_active.assert_called_with(True)

        widget.get_active.return_value = True
        dict_tab.on_whisper_mode_toggled(widget)
        parent.set_use_remote_whisper.assert_called_with(True, source=dict_tab)
