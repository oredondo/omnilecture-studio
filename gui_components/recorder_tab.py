import os
import time
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
from detector import ZoomDetector
from video_recorder import VideoRecorder
from audio_recorder import AudioRecorder
from processor import MediaProcessor

logger = logging.getLogger("OmniLectureGUI.RecorderTab")


class RecorderTab(Gtk.Box):
    """Tab component managing Zoom call detection, manual screen recording, timer, and compression."""

    def __init__(self, parent_window: Gtk.Window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        self.parent_window = parent_window

        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        self.set_margin_bottom(20)

        # Core logic instances
        self.detector = ZoomDetector()
        self.processor = MediaProcessor()
        self.video_recorder = None
        self.audio_recorder = None

        # State flags
        self.is_recording = False
        self.is_waiting_zoom = False
        self.is_processing = False
        self.recording_start_time = None

        # Sources
        self.timer_timeout_id = None
        self.zoom_poll_timeout_id = None

        self._build_ui()

    def _build_ui(self):
        # Mode Selection Frame
        mode_frame = Gtk.Frame(label="Recording Mode")
        mode_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mode_box.set_margin_start(15)
        mode_box.set_margin_end(15)
        mode_box.set_margin_top(10)
        mode_box.set_margin_bottom(10)
        mode_frame.add(mode_box)
        self.pack_start(mode_frame, False, False, 0)

        self.radio_auto = Gtk.RadioButton.new_with_label_from_widget(None, "Automatic (Detect Zoom)")
        self.radio_manual = Gtk.RadioButton.new_with_label_from_widget(self.radio_auto, "Manual (Record Full Screen)")
        mode_box.pack_start(self.radio_auto, False, False, 0)
        mode_box.pack_start(self.radio_manual, False, False, 0)

        # Separator
        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        # Legal Disclaimer Notice
        lbl_disclaimer = Gtk.Label()
        lbl_disclaimer.set_markup(
            "<small>⚖️ <i><b>Mandatory legal notice:</b> It is legally required to inform all "
            "participants before recording any video call.</i></small>"
        )
        lbl_disclaimer.set_line_wrap(True)
        lbl_disclaimer.set_xalign(0)
        self.pack_start(lbl_disclaimer, False, False, 2)

        # Display Box
        display_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.pack_start(display_box, True, True, 0)

        self.timer_label = Gtk.Label(label="00:00:00")
        self.timer_label.modify_font(Pango.FontDescription("monospace bold 28"))
        display_box.pack_start(self.timer_label, True, True, 0)

        self.status_label = Gtk.Label(label="Ready to record")
        self.status_label.modify_font(Pango.FontDescription("italic 10"))
        display_box.pack_start(self.status_label, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_text("")
        self.progress_bar.set_show_text(True)
        self.progress_bar.set_no_show_all(True)
        self.progress_bar.hide()
        display_box.pack_start(self.progress_bar, False, False, 5)

        # Action Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        btn_box.set_homogeneous(True)
        self.pack_start(btn_box, False, False, 0)

        self.btn_record = Gtk.Button(label="Record")
        self.btn_record.get_style_context().add_class("suggested-action")
        self.btn_record.connect("clicked", self.on_record_clicked)
        btn_box.pack_start(self.btn_record, True, True, 0)

        self.btn_stop = Gtk.Button(label="Stop")
        self.btn_stop.get_style_context().add_class("destructive-action")
        self.btn_stop.set_sensitive(False)
        self.btn_stop.connect("clicked", self.on_stop_clicked)
        btn_box.pack_start(self.btn_stop, True, True, 0)

    def on_record_clicked(self, widget):
        self.radio_auto.set_sensitive(False)
        self.radio_manual.set_sensitive(False)
        self.btn_record.set_sensitive(False)
        self.btn_stop.set_sensitive(True)
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(False)

        if self.radio_manual.get_active():
            self.status_label.set_text("Starting manual recording...")
            if self.start_recording_session():
                self.status_label.set_text("Recording full screen...")
        else:
            self.is_waiting_zoom = True
            self.status_label.set_text("Waiting for Zoom call...")
            self.zoom_poll_timeout_id = GLib.timeout_add_seconds(config.POLLING_INTERVAL, self.poll_zoom_status)

    def on_stop_clicked(self, widget):
        self.btn_stop.set_sensitive(False)
        if self.is_waiting_zoom and not self.is_recording:
            logger.info("Zoom waiting canceled by user.")
            if self.zoom_poll_timeout_id:
                GLib.source_remove(self.zoom_poll_timeout_id)
                self.zoom_poll_timeout_id = None
            self.is_waiting_zoom = False
            self.reset_ui_state("Recording canceled")
        else:
            self.status_label.set_text("Processing and compressing recording...")
            self.stop_recording_session_and_process()

    def start_recording_session(self) -> bool:
        video_temp_template = f"temp_zoom_video_{int(time.time())}"
        audio_temp_path = os.path.join(config.TEMP_DIR, f"temp_zoom_audio_{int(time.time())}.ogg")

        try:
            self.video_recorder = VideoRecorder(filename_template=video_temp_template)
            self.audio_recorder = AudioRecorder(output_path=audio_temp_path)

            if not self.video_recorder.start():
                self.reset_ui_state("Error: Video recorder failed")
                return False

            if not self.audio_recorder.start():
                self.video_recorder.stop()
                self.reset_ui_state("Error: Audio recorder failed")
                return False

            self.is_recording = True
            self.recording_start_time = datetime.now()
            self.timer_timeout_id = GLib.timeout_add_seconds(1, self.update_timer)
            return True
        except Exception as e:
            logger.error(f"Error starting recording session: {e}")
            self.reset_ui_state("Error starting recorders")
            return False

    def stop_recording_session_and_process(self):
        if not self.is_recording:
            return

        self.is_recording = False
        if self.timer_timeout_id:
            GLib.source_remove(self.timer_timeout_id)
            self.timer_timeout_id = None
        if self.zoom_poll_timeout_id:
            GLib.source_remove(self.zoom_poll_timeout_id)
            self.zoom_poll_timeout_id = None

        video_file = self.video_recorder.stop() if self.video_recorder else None
        audio_file = self.audio_recorder.stop() if self.audio_recorder else None

        logger.info("Recording stopped. Spawning merge and compression thread...")
        self.is_processing = True
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_text("Initializing compression...")
        self.progress_bar.show()

        threading.Thread(
            target=self.merge_and_compress_worker,
            args=(video_file, audio_file),
            daemon=True
        ).start()

    def merge_and_compress_worker(self, video_file: str, audio_file: str):
        time.sleep(2.0)
        if not video_file or not os.path.exists(video_file) or not audio_file or not os.path.exists(audio_file):
            GLib.idle_add(self.on_processing_complete, False, "Temporary files not found")
            return

        now = datetime.now()
        filename = f"{now.strftime(config.FILENAME_FORMAT)}.mp4"
        output_path = os.path.join(config.OUTPUT_DIR, filename)

        def progress_cb(progress):
            GLib.idle_add(self.update_progress, progress)

        success = self.processor.merge_and_compress(video_file, audio_file, output_path, progress_callback=progress_cb)
        GLib.idle_add(self.on_processing_complete, success, filename if success else "FFmpeg error")

    def update_progress(self, progress: float):
        self.progress_bar.set_fraction(progress)
        percentage = int(progress * 100)
        self.progress_bar.set_text(f"Compressing... {percentage}%")

    def on_processing_complete(self, success: bool, info: str):
        self.is_processing = False
        self.progress_bar.hide()
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(True)
        if success:
            logger.info(f"Processing complete: {info}")
            self.reset_ui_state(f"Recording saved: {info}")
        else:
            logger.error(f"Processing failed: {info}")
            self.reset_ui_state(f"Error: {info}")

    def poll_zoom_status(self) -> bool:
        if not self.is_waiting_zoom:
            return False
        meeting_active = self.detector.is_meeting_active()
        if meeting_active and not self.is_recording:
            logger.info("Zoom call detected by GUI poll!")
            self.status_label.set_text("Recording Zoom call...")
            self.start_recording_session()
        elif not meeting_active and self.is_recording:
            logger.info("Zoom call ended. Stopping GUI recording...")
            self.status_label.set_text("Call ended. Compressing...")
            self.stop_recording_session_and_process()
            self.is_waiting_zoom = True
        return True

    def update_timer(self) -> bool:
        if not self.is_recording or not self.recording_start_time:
            return False
        delta = datetime.now() - self.recording_start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.timer_label.set_text(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        return True

    def reset_ui_state(self, status_text: str):
        self.radio_auto.set_sensitive(True)
        self.radio_manual.set_sensitive(True)
        self.btn_record.set_sensitive(True)
        self.btn_stop.set_sensitive(False)
        self.status_label.set_text(status_text)
        self.timer_label.set_text("00:00:00")
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(True)

    def cleanup(self):
        """Clean up active timers and stop ongoing recordings."""
        if self.timer_timeout_id:
            GLib.source_remove(self.timer_timeout_id)
            self.timer_timeout_id = None
        if self.zoom_poll_timeout_id:
            GLib.source_remove(self.zoom_poll_timeout_id)
            self.zoom_poll_timeout_id = None
        if self.is_recording:
            if self.video_recorder:
                self.video_recorder.stop()
            if self.audio_recorder:
                self.audio_recorder.stop()
