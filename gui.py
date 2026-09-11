import os
import sys
import glob
import logging

# Auto-inject project's .venv site-packages into sys.path if launched with system python
_proj_root = os.path.dirname(os.path.abspath(__file__))
_venv_sites = glob.glob(os.path.join(_proj_root, ".venv", "lib", "python3.*", "site-packages"))
for _sp in _venv_sites:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import gi
try:
    gi.require_version('Gtk', '3.0')
except ValueError:
    pass
from gi.repository import Gtk, GLib

# Set Application ID and Window Class Name for GNOME/Wayland taskbar grouping
try:
    GLib.set_prgname("zoom-screen-recorder")
    GLib.set_application_name("Grabador y Apuntes EIR")
except Exception:
    pass

import config
from gui_components.dialogs import DialogUtils
from gui_components.recorder_tab import RecorderTab
from gui_components.eir_notes_tab import EIRNotesTab
from gui_components.handwritten_tab import HandwrittenTab
from gui_components.dictation_tab import DictationTab

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE)
    ]
)
logger = logging.getLogger("ZoomRecorderGUI")


class ZoomRecorderGUI(Gtk.Window):
    """Native GTK 3 Graphical User Interface for Zoom and Screen Recorder with EIR Notes pipeline."""

    def __init__(self):
        super().__init__(title="Grabador y Apuntes EIR")
        self.set_default_size(460, 420)
        self.set_resizable(True)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Set Window Icons for taskbar dock matching
        icon_256 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon_256.png")
        if os.path.exists(icon_256):
            try:
                self.set_icon_from_file(icon_256)
                Gtk.Window.set_default_icon_from_file(icon_256)
            except Exception as e:
                logger.warning(f"Could not load window icon: {e}")

        self._build_ui()

        self.connect("delete-event", self.on_delete_event)
        self.connect("destroy", self.on_destroy)

    def _build_ui(self):
        # HeaderBar (GNOME Native Style)
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Zoom & Screen Recorder"
        hb.props.subtitle = "EIR Apuntes y Memorización"
        self.set_titlebar(hb)

        # Whisper Endpoint / Local Toggle Button in HeaderBar
        self.btn_whisper_toggle = Gtk.ToggleButton()
        try:
            import pipeline_config
            initial_remote = getattr(pipeline_config, "USE_REMOTE_WHISPER", True)
        except Exception:
            initial_remote = True
        self.btn_whisper_toggle.set_active(initial_remote)
        self._update_whisper_toggle_label(initial_remote)
        self.btn_whisper_toggle.connect("toggled", self.on_whisper_toggle_changed)
        hb.pack_end(self.btn_whisper_toggle)

        # Notebook for Modular Tabs
        self.notebook = Gtk.Notebook()
        self.add(self.notebook)

        # Tab 1: Grabador
        self.recorder_tab = RecorderTab(parent_window=self)
        self.notebook.append_page(self.recorder_tab, Gtk.Label(label="Grabador"))

        # Tab 2: Apuntes EIR
        self.eir_tab = EIRNotesTab(parent_window=self)
        self.notebook.append_page(self.eir_tab, Gtk.Label(label="Apuntes EIR"))

        # Tab 3: Manuscritos
        self.handwritten_tab = HandwrittenTab(parent_window=self)
        self.notebook.append_page(self.handwritten_tab, Gtk.Label(label="Manuscritos"))

        # Tab 4: Dictado por Voz
        self.dictation_tab = DictationTab(parent_window=self)
        self.notebook.append_page(self.dictation_tab, Gtk.Label(label="Dictado"))

    def _update_whisper_toggle_label(self, is_remote: bool):
        if is_remote:
            self.btn_whisper_toggle.set_label("🌐 Whisper Remoto")
            self.btn_whisper_toggle.set_tooltip_text(
                "Whisper Remoto activo (https://leria.gal/api/v1/audio/transcriptions).\n"
                "Haz clic para cambiar a Whisper Local (offline CPU)."
            )
            self.btn_whisper_toggle.get_style_context().add_class("suggested-action")
        else:
            self.btn_whisper_toggle.set_label("💻 Whisper Local")
            self.btn_whisper_toggle.set_tooltip_text(
                "Whisper Local activo: faster-whisper (CPU int8).\n"
                "Haz clic para cambiar a Whisper Remoto (Leria API)."
            )
            self.btn_whisper_toggle.get_style_context().remove_class("suggested-action")

    def on_whisper_toggle_changed(self, widget):
        is_remote = widget.get_active()
        self.set_use_remote_whisper(is_remote, source=self.btn_whisper_toggle)

    def set_use_remote_whisper(self, is_remote: bool, source=None):
        try:
            import pipeline_config
            pipeline_config.USE_REMOTE_WHISPER = is_remote
        except Exception:
            pass

        if source != getattr(self, "btn_whisper_toggle", None) and hasattr(self, "btn_whisper_toggle"):
            self.btn_whisper_toggle.handler_block_by_func(self.on_whisper_toggle_changed)
            self.btn_whisper_toggle.set_active(is_remote)
            self._update_whisper_toggle_label(is_remote)
            self.btn_whisper_toggle.handler_unblock_by_func(self.on_whisper_toggle_changed)
        elif hasattr(self, "btn_whisper_toggle"):
            self._update_whisper_toggle_label(is_remote)

        if hasattr(self, "eir_tab") and hasattr(self.eir_tab, "set_remote_whisper"):
            self.eir_tab.set_remote_whisper(is_remote)
        if hasattr(self, "dictation_tab") and hasattr(self.dictation_tab, "set_remote_whisper"):
            self.dictation_tab.set_remote_whisper(is_remote)

    def on_delete_event(self, widget, event):
        if self.recorder_tab.is_recording:
            confirm = DialogUtils.ask_confirmation(
                self,
                "Grabación en curso",
                "Hay una grabación activa. ¿Deseas detenerla y salir?"
            )
            if confirm:
                self.recorder_tab.stop_recording_session_and_process()
                return False
            return True

        if self.recorder_tab.is_processing:
            DialogUtils.show_error(
                self,
                "Procesamiento en curso",
                "Espere a que finalice la compresión antes de cerrar."
            )
            return True

        if (self.eir_tab.is_running_pipeline or
                self.handwritten_tab.is_running_handwritten or
                self.dictation_tab.is_running):
            DialogUtils.show_error(
                self,
                "Generación en curso",
                "Espere a que finalice la generación de apuntes antes de cerrar."
            )
            return True

        return False

    def on_destroy(self, widget):
        self.recorder_tab.cleanup()
        Gtk.main_quit()


def main():
    app = ZoomRecorderGUI()
    app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
