import os
import logging
import threading

import gi
try:
    gi.require_version('Gtk', '3.0')
except ValueError:
    pass
from gi.repository import Gtk, GLib, Pango

from gui_components.dialogs import DialogUtils

logger = logging.getLogger("OmniLectureGUI.NotesTab")


class EIRNotesTab(Gtk.Box):
    """Tab component managing class notes & Anki flashcard generation pipeline."""

    def __init__(self, parent_window: Gtk.Window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        self.parent_window = parent_window

        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        self.set_margin_bottom(20)

        self.is_running_pipeline = False
        self._build_ui()

    def _build_ui(self):
        pipe_title = Gtk.Label()
        pipe_title.set_markup("<b>Class Notes & Anki Generation</b>")
        pipe_title.modify_font(Pango.FontDescription("bold 12"))
        self.pack_start(pipe_title, False, False, 5)

        grid = Gtk.Grid(row_spacing=10, column_spacing=15)
        grid.set_column_homogeneous(False)
        self.pack_start(grid, False, False, 5)

        # Video Selector
        lbl_video = Gtk.Label(label="Video File (.mp4):")
        lbl_video.set_xalign(0)
        self.video_chooser = Gtk.FileChooserButton(title="Select Video File (.mp4)", action=Gtk.FileChooserAction.OPEN)
        filter_mp4 = Gtk.FileFilter()
        filter_mp4.set_name("MP4 Files (*.mp4)")
        filter_mp4.add_pattern("*.mp4")
        self.video_chooser.add_filter(filter_mp4)
        self.video_chooser.connect("file-set", self.on_video_file_set)

        grid.attach(lbl_video, 0, 0, 1, 1)
        grid.attach(self.video_chooser, 1, 0, 1, 1)
        self.video_chooser.set_hexpand(True)

        # Audio Selector
        lbl_audio = Gtk.Label(label="Audio File (.mp3):")
        lbl_audio.set_xalign(0)
        self.audio_chooser = Gtk.FileChooserButton(title="Select Audio File (.mp3)", action=Gtk.FileChooserAction.OPEN)
        filter_mp3 = Gtk.FileFilter()
        filter_mp3.set_name("MP3 Files (*.mp3)")
        filter_mp3.add_pattern("*.mp3")
        self.audio_chooser.add_filter(filter_mp3)

        grid.attach(lbl_audio, 0, 1, 1, 1)
        grid.attach(self.audio_chooser, 1, 1, 1, 1)

        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        pipe_display = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.pack_start(pipe_display, True, True, 0)

        # Anki Checkbox
        self.chk_anki = Gtk.CheckButton(label="Generate spaced-repetition Anki flashcards")
        try:
            import pipeline_config
            self.chk_anki.set_active(getattr(pipeline_config, "GENERATE_ANKI", True))
        except Exception:
            self.chk_anki.set_active(True)
        pipe_display.pack_start(self.chk_anki, False, False, 5)

        # Whisper Remote vs Local Checkbox
        self.chk_remote_whisper = Gtk.CheckButton(label="Use Remote Whisper (Leria API)")
        self.chk_remote_whisper.set_tooltip_text(
            "Checked (default): Transcribes using https://leria.gal/api/v1/audio/transcriptions.\n"
            "Unchecked: Transcribes with local CPU Whisper (faster-whisper int8)."
        )
        try:
            import pipeline_config
            self.chk_remote_whisper.set_active(getattr(pipeline_config, "USE_REMOTE_WHISPER", True))
        except Exception:
            self.chk_remote_whisper.set_active(True)
        self.chk_remote_whisper.connect("toggled", self.on_whisper_mode_toggled)
        pipe_display.pack_start(self.chk_remote_whisper, False, False, 2)

        self.pipeline_status_label = Gtk.Label(label="Select files and click Generate")
        self.pipeline_status_label.set_line_wrap(True)
        self.pipeline_status_label.set_justify(Gtk.Justification.CENTER)
        self.pipeline_status_label.modify_font(Pango.FontDescription("monospace bold 10"))
        pipe_display.pack_start(self.pipeline_status_label, True, True, 0)

        self.pipeline_progress_bar = Gtk.ProgressBar()
        self.pipeline_progress_bar.set_text("")
        self.pipeline_progress_bar.set_show_text(True)
        self.pipeline_progress_bar.set_no_show_all(True)
        self.pipeline_progress_bar.hide()
        pipe_display.pack_start(self.pipeline_progress_bar, False, False, 5)

        self.btn_generate = Gtk.Button(label="Generate Study Notes & Anki")
        self.btn_generate.get_style_context().add_class("suggested-action")
        self.btn_generate.connect("clicked", self.on_generate_clicked)
        self.pack_start(self.btn_generate, False, False, 0)

    def set_remote_whisper(self, is_remote: bool):
        if hasattr(self, "chk_remote_whisper"):
            self.chk_remote_whisper.handler_block_by_func(self.on_whisper_mode_toggled)
            self.chk_remote_whisper.set_active(is_remote)
            self.chk_remote_whisper.handler_unblock_by_func(self.on_whisper_mode_toggled)

    def on_whisper_mode_toggled(self, widget):
        is_remote = widget.get_active()
        if hasattr(self.parent_window, "set_use_remote_whisper"):
            self.parent_window.set_use_remote_whisper(is_remote, source=self)

    def on_video_file_set(self, widget):
        video_path = widget.get_filename()
        if not video_path:
            return
        base, _ = os.path.splitext(video_path)
        audio_path = base + ".mp3"
        if os.path.exists(audio_path):
            logger.info(f"Auto-selected matching audio: {audio_path}")
            self.audio_chooser.set_filename(audio_path)

    def on_generate_clicked(self, widget):
        video = self.video_chooser.get_filename()
        audio = self.audio_chooser.get_filename()

        if not video or not audio:
            DialogUtils.show_error(
                self.parent_window,
                "Missing Files",
                "Please select both the video (.mp4) and audio (.mp3) files before proceeding."
            )
            return

        anki_enabled = self.chk_anki.get_active()
        remote_whisper = self.chk_remote_whisper.get_active()
        self.btn_generate.set_sensitive(False)
        self.video_chooser.set_sensitive(False)
        self.audio_chooser.set_sensitive(False)
        self.chk_anki.set_sensitive(False)
        self.chk_remote_whisper.set_sensitive(False)
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(False)

        self.is_running_pipeline = True
        self.pipeline_progress_bar.set_fraction(0.0)
        self.pipeline_progress_bar.set_text("Starting analysis...")
        self.pipeline_progress_bar.show()

        threading.Thread(
            target=self._pipeline_worker,
            args=(video, audio, anki_enabled, remote_whisper),
            daemon=True
        ).start()

    def _pipeline_worker(self, video_path: str, audio_path: str, anki_enabled: bool, remote_whisper: bool):
        def progress_cb(message, progress):
            GLib.idle_add(self._update_pipeline_ui, message, progress)

        try:
            from pipeline.generate_notes import NotesGenerator
            generator = NotesGenerator(video_path, audio_path, generate_anki=anki_enabled, use_remote_whisper=remote_whisper)
            _, anki_path = generator.run(status_callback=progress_cb)
            status_msg = "Notes and Anki cards generated successfully!" if anki_path else "Notes generated successfully! (Without Anki)"
            GLib.idle_add(self._on_pipeline_complete, True, status_msg)
        except Exception as e:
            logger.exception("Pipeline failed in GUI:")
            GLib.idle_add(self._on_pipeline_complete, False, f"Error: {str(e)}")

    def _update_pipeline_ui(self, message: str, progress: float):
        self.pipeline_status_label.set_text(message)
        self.pipeline_progress_bar.set_fraction(progress)
        percentage = int(progress * 100)
        self.pipeline_progress_bar.set_text(f"Progress: {percentage}%")

    def _on_pipeline_complete(self, success: bool, status_text: str):
        self.is_running_pipeline = False
        self.pipeline_progress_bar.hide()
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(True)

        self.btn_generate.set_sensitive(True)
        self.video_chooser.set_sensitive(True)
        self.audio_chooser.set_sensitive(True)
        self.chk_anki.set_sensitive(True)
        self.chk_remote_whisper.set_sensitive(True)

        self.pipeline_status_label.set_text(status_text)
        self.video_chooser.unselect_all()
        self.audio_chooser.unselect_all()

        if success:
            DialogUtils.show_info(self.parent_window, "Process Completed", status_text)
        else:
            DialogUtils.show_error(self.parent_window, "Processing Error", status_text)
