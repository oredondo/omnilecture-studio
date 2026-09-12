import os
import logging
import threading
from datetime import datetime

import gi
try:
    gi.require_version('Gtk', '3.0')
except ValueError:
    pass
from gi.repository import Gtk, GLib, Pango

import config
from audio_recorder import AudioRecorder
from gui_components.dialogs import DialogUtils

logger = logging.getLogger("OmniLectureGUI.DictationTab")


class DictationTab(Gtk.Box):
    """Tab managing live voice dictation (Record/Pause/Resume), MP3 compression, and AI notes."""

    def __init__(self, parent_window: Gtk.Window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent_window = parent_window

        self.set_margin_start(18)
        self.set_margin_end(18)
        self.set_margin_top(15)
        self.set_margin_bottom(15)

        self.is_running = False
        self.is_recording = False
        self.audio_recorder = None
        self.recording_start_time = None
        self.timer_timeout_id = None

        self._build_ui()

    def _build_ui(self):
        title = Gtk.Label()
        title.set_markup("<b>Voice Dictation & AI Study Notes</b>")
        title.modify_font(Pango.FontDescription("bold 12"))
        self.pack_start(title, False, False, 0)

        # Microphone Recording Group
        mic_frame = Gtk.Frame(label="Live Dictation Recording")
        mic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mic_box.set_margin_start(12)
        mic_box.set_margin_end(12)
        mic_box.set_margin_top(8)
        mic_box.set_margin_bottom(8)
        mic_frame.add(mic_box)
        self.pack_start(mic_frame, False, False, 0)

        # Timer Display
        self.timer_label = Gtk.Label(label="00:00:00")
        self.timer_label.modify_font(Pango.FontDescription("monospace bold 20"))
        mic_box.pack_start(self.timer_label, False, False, 0)

        # Buttons Box (Record / Pause / Stop)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_homogeneous(True)
        mic_box.pack_start(btn_box, False, False, 0)

        self.btn_rec = Gtk.Button(label="Record")
        self.btn_rec.get_style_context().add_class("suggested-action")
        self.btn_rec.connect("clicked", self.on_rec_clicked)
        btn_box.pack_start(self.btn_rec, True, True, 0)

        self.btn_pause = Gtk.Button(label="Pause")
        self.btn_pause.set_sensitive(False)
        self.btn_pause.connect("clicked", self.on_pause_clicked)
        btn_box.pack_start(self.btn_pause, True, True, 0)

        self.btn_stop = Gtk.Button(label="Finish & Generate")
        self.btn_stop.get_style_context().add_class("destructive-action")
        self.btn_stop.set_sensitive(False)
        self.btn_stop.connect("clicked", self.on_stop_clicked)
        btn_box.pack_start(self.btn_stop, True, True, 0)

        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # File Selection Alternative
        file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl_audio = Gtk.Label(label="Or Select Audio / Raw Text:")
        self.audio_chooser = Gtk.FileChooserButton(
            title="Select Dictation Audio or Text File (.wav, .mp3, .txt)",
            action=Gtk.FileChooserAction.OPEN
        )
        filter_audio = Gtk.FileFilter()
        filter_audio.set_name("Audio and Text Files (*.wav, *.mp3, *.txt...)")
        for ext in ["*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a", "*.txt"]:
            filter_audio.add_pattern(ext)
        self.audio_chooser.add_filter(filter_audio)
        file_box.pack_start(lbl_audio, False, False, 0)
        file_box.pack_start(self.audio_chooser, True, True, 0)
        self.pack_start(file_box, False, False, 0)

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
        self.pack_start(self.chk_remote_whisper, False, False, 0)

        # Status & Progress
        display_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.pack_start(display_box, True, True, 0)

        self.status_label = Gtk.Label(label="Record your dictation or select a file to process")
        self.status_label.set_line_wrap(True)
        self.status_label.set_justify(Gtk.Justification.CENTER)
        self.status_label.modify_font(Pango.FontDescription("monospace bold 9"))
        display_box.pack_start(self.status_label, True, True, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_text("")
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_no_show_all(True)
        self.progress_bar.hide()
        display_box.pack_start(self.progress_bar, False, False, 2)

        self.btn_file_generate = Gtk.Button(label="Generate from Selected File")
        self.btn_file_generate.connect("clicked", self.on_file_generate_clicked)
        self.pack_start(self.btn_file_generate, False, False, 0)

    def set_remote_whisper(self, is_remote: bool):
        if hasattr(self, "chk_remote_whisper"):
            self.chk_remote_whisper.handler_block_by_func(self.on_whisper_mode_toggled)
            self.chk_remote_whisper.set_active(is_remote)
            self.chk_remote_whisper.handler_unblock_by_func(self.on_whisper_mode_toggled)

    def on_whisper_mode_toggled(self, widget):
        is_remote = widget.get_active()
        if hasattr(self.parent_window, "set_use_remote_whisper"):
            self.parent_window.set_use_remote_whisper(is_remote, source=self)

    def on_rec_clicked(self, widget):
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_dir = os.path.join(config.OUTPUT_DIR, "apuntes_dictados", "bruto")
        os.makedirs(raw_dir, exist_ok=True)
        audio_temp_path = os.path.join(raw_dir, f"{now_str}_dictation_raw.wav")

        self.audio_recorder = AudioRecorder(output_path=audio_temp_path, mic_only=True)
        if not self.audio_recorder.start():
            DialogUtils.show_error(self.parent_window, "Microphone Error", "Could not start microphone recording.")
            return

        self.is_recording = True
        self.recording_start_time = datetime.now()
        self.timer_timeout_id = GLib.timeout_add_seconds(1, self._update_timer)

        self.btn_rec.set_sensitive(False)
        self.btn_pause.set_sensitive(True)
        self.btn_stop.set_sensitive(True)
        self.btn_file_generate.set_sensitive(False)
        self.audio_chooser.set_sensitive(False)
        self.chk_remote_whisper.set_sensitive(False)
        self.status_label.set_text("Recording dictation in high fidelity (saving complete audio)...")

    def on_pause_clicked(self, widget):
        if not self.audio_recorder:
            return

        if self.audio_recorder.is_paused():
            self.audio_recorder.resume()
            self.btn_pause.set_label("Pause")
            self.status_label.set_text("Dictation recording resumed...")
        else:
            self.audio_recorder.pause()
            self.btn_pause.set_label("Resume")
            self.status_label.set_text("Dictation recording paused")

    def on_stop_clicked(self, widget):
        if not self.is_recording or not self.audio_recorder:
            return

        elapsed_sec = 0
        if self.recording_start_time:
            elapsed_sec = (datetime.now() - self.recording_start_time).total_seconds()

        self.is_recording = False
        if self.timer_timeout_id:
            GLib.source_remove(self.timer_timeout_id)
            self.timer_timeout_id = None

        temp_audio_file = self.audio_recorder.stop()
        self.btn_rec.set_sensitive(True)
        self.btn_pause.set_sensitive(False)
        self.btn_stop.set_sensitive(False)
        self.btn_file_generate.set_sensitive(True)
        self.audio_chooser.set_sensitive(True)
        self.chk_remote_whisper.set_sensitive(True)
        self.btn_pause.set_label("Pause")

        if elapsed_sec < 2.0 or not os.path.exists(temp_audio_file) or os.path.getsize(temp_audio_file) < 1000:
            DialogUtils.show_error(
                self.parent_window,
                "Recording Too Short",
                "The recording lasted less than 2 seconds or contained no audio. "
                "Please speak for at least 3-5 seconds to process dictation."
            )
            self.status_label.set_text("Recording canceled (duration < 2 seconds).")
            return

        self.btn_rec.set_sensitive(False)
        self.btn_file_generate.set_sensitive(False)
        self.audio_chooser.set_sensitive(False)
        self.chk_remote_whisper.set_sensitive(False)

        self.is_running = True
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_text("Processing audio and archiving recording...")
        self.progress_bar.show()

        threading.Thread(
            target=self._process_recorded_dictation_worker,
            args=(temp_audio_file,),
            daemon=True
        ).start()

    def _process_recorded_dictation_worker(self, input_file: str):
        def progress_cb(message, progress):
            GLib.idle_add(self._update_ui, message, progress)

        try:
            from pipeline.dictation_notes import VoiceDictationNotesGenerator
            use_remote = self.chk_remote_whisper.get_active()
            generator = VoiceDictationNotesGenerator(use_remote_whisper=use_remote)

            md_path, raw_text_path, backup_mp3 = generator.run_from_file(input_file, status_callback=progress_cb)

            if backup_mp3:
                status_msg = (
                    f"Notes generated successfully!\n"
                    f"Original Audio: {os.path.basename(input_file)}\n"
                    f"MP3 Audio: {os.path.basename(backup_mp3)}"
                )
            else:
                status_msg = (
                    f"Notes generated from raw text!\n"
                    f"Raw Text: {os.path.basename(raw_text_path)}"
                )
            GLib.idle_add(self._on_complete, True, status_msg)
        except Exception as e:
            logger.exception("Dictation processing failed:")
            GLib.idle_add(self._on_complete, False, f"Error: {str(e)}")

    def on_file_generate_clicked(self, widget):
        audio_path = self.audio_chooser.get_filename()
        if not audio_path:
            DialogUtils.show_error(self.parent_window, "No File Selected", "Please select an audio file.")
            return

        self.btn_file_generate.set_sensitive(False)
        self.btn_rec.set_sensitive(False)
        self.audio_chooser.set_sensitive(False)
        self.chk_remote_whisper.set_sensitive(False)
        self.is_running = True
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_text("Processing audio file...")
        self.progress_bar.show()

        threading.Thread(
            target=self._process_recorded_dictation_worker,
            args=(audio_path,),
            daemon=True
        ).start()

    def _update_timer(self) -> bool:
        if not self.is_recording or not self.recording_start_time:
            return False
        if self.audio_recorder and self.audio_recorder.is_paused():
            return True
        delta = datetime.now() - self.recording_start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.timer_label.set_text(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        return True

    def _update_ui(self, message: str, progress: float):
        self.status_label.set_text(message)
        self.progress_bar.set_fraction(progress)
        percentage = int(progress * 100)
        self.progress_bar.set_text(f"Progress: {percentage}%")

    def _on_complete(self, success: bool, status_text: str):
        self.is_running = False
        self.progress_bar.hide()

        self.btn_rec.set_sensitive(True)
        self.btn_pause.set_sensitive(False)
        self.btn_pause.set_label("Pause")
        self.btn_stop.set_sensitive(False)
        self.btn_file_generate.set_sensitive(True)
        self.audio_chooser.set_sensitive(True)
        self.chk_remote_whisper.set_sensitive(True)

        self.status_label.set_text(status_text)
        self.timer_label.set_text("00:00:00")
        self.audio_chooser.unselect_all()

        if success:
            DialogUtils.show_info(self.parent_window, "Dictation Completed", status_text)
        else:
            DialogUtils.show_error(self.parent_window, "Processing Error", status_text)
