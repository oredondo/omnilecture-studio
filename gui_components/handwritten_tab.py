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

logger = logging.getLogger("OmniLectureGUI.HandwrittenTab")


class HandwrittenTab(Gtk.Box):
    """Tab component managing handwritten note photo OCR & Markdown digitization."""

    def __init__(self, parent_window: Gtk.Window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        self.parent_window = parent_window

        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        self.set_margin_bottom(20)

        self.is_running_handwritten = False
        self.selected_images = []
        self._build_ui()

    def _build_ui(self):
        hw_title = Gtk.Label()
        hw_title.set_markup("<b>Handwritten Notes Digitization</b>")
        hw_title.modify_font(Pango.FontDescription("bold 12"))
        self.pack_start(hw_title, False, False, 5)

        hw_desc = Gtk.Label(label="Converts handwritten note photos into Markdown (.md) and Word (.docx) with Zero Invention.")
        hw_desc.set_line_wrap(True)
        hw_desc.set_justify(Gtk.Justification.CENTER)
        hw_desc.modify_font(Pango.FontDescription("italic 9"))
        self.pack_start(hw_desc, False, False, 0)

        hw_file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pack_start(hw_file_box, False, False, 5)

        self.btn_select_images = Gtk.Button(label="Select Note Photos (.jpg, .png...)")
        self.btn_select_images.connect("clicked", self.on_select_images_clicked)
        hw_file_box.pack_start(self.btn_select_images, False, False, 0)

        self.lbl_handwritten_count = Gtk.Label(label="0 images selected")
        self.lbl_handwritten_count.modify_font(Pango.FontDescription("monospace 9"))
        hw_file_box.pack_start(self.lbl_handwritten_count, False, False, 0)

        self.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 5)

        hw_display = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.pack_start(hw_display, True, True, 0)

        self.handwritten_status_label = Gtk.Label(label="Select handwritten photos and click Generate")
        self.handwritten_status_label.set_line_wrap(True)
        self.handwritten_status_label.set_justify(Gtk.Justification.CENTER)
        self.handwritten_status_label.modify_font(Pango.FontDescription("monospace bold 10"))
        hw_display.pack_start(self.handwritten_status_label, True, True, 0)

        self.handwritten_progress_bar = Gtk.ProgressBar()
        self.handwritten_progress_bar.set_text("")
        self.handwritten_progress_bar.set_show_text(True)
        self.handwritten_progress_bar.set_no_show_all(True)
        self.handwritten_progress_bar.hide()
        hw_display.pack_start(self.handwritten_progress_bar, False, False, 5)

        self.btn_generate = Gtk.Button(label="Generate Handwritten Notes")
        self.btn_generate.get_style_context().add_class("suggested-action")
        self.btn_generate.connect("clicked", self.on_generate_handwritten_clicked)
        self.pack_start(self.btn_generate, False, False, 0)

    def on_select_images_clicked(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Select Handwritten Note Photos",
            parent=self.parent_window,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.ACCEPT
        )
        dialog.set_select_multiple(True)

        filter_images = Gtk.FileFilter()
        filter_images.set_name("Images (*.jpg, *.png, *.heic, *.webp...)")
        for ext in ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp", "*.heic", "*.HEIC", "*.heif", "*.HEIF"]:
            filter_images.add_pattern(ext)
        dialog.add_filter(filter_images)

        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            self.selected_images = dialog.get_filenames()
            count = len(self.selected_images)
            self.lbl_handwritten_count.set_text(f"{count} images selected")
            logger.info(f"Selected {count} handwritten note images for processing.")
        dialog.destroy()

    def on_generate_handwritten_clicked(self, widget):
        if not self.selected_images:
            DialogUtils.show_error(
                self.parent_window,
                "No Images Selected",
                "Please select at least one photo of handwritten notes before proceeding."
            )
            return

        self.btn_generate.set_sensitive(False)
        self.btn_select_images.set_sensitive(False)
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(False)

        self.is_running_handwritten = True
        self.handwritten_progress_bar.set_fraction(0.0)
        self.handwritten_progress_bar.set_text("Starting handwritten analysis...")
        self.handwritten_progress_bar.show()

        threading.Thread(
            target=self._handwritten_worker,
            args=(self.selected_images,),
            daemon=True
        ).start()

    def _handwritten_worker(self, image_paths: list):
        def progress_cb(message, progress):
            GLib.idle_add(self._update_handwritten_ui, message, progress)

        try:
            from pipeline.handwritten_notes import HandwrittenNotesGenerator
            generator = HandwrittenNotesGenerator(image_paths)
            md_path, _ = generator.run(status_callback=progress_cb)
            status_msg = f"Handwritten notes generated successfully in:\n{os.path.basename(md_path)}"
            GLib.idle_add(self._on_handwritten_complete, True, status_msg)
        except Exception as e:
            logger.exception("Handwritten Notes pipeline failed in GUI:")
            GLib.idle_add(self._on_handwritten_complete, False, f"Error: {str(e)}")

    def _update_handwritten_ui(self, message: str, progress: float):
        self.handwritten_status_label.set_text(message)
        self.handwritten_progress_bar.set_fraction(progress)
        percentage = int(progress * 100)
        self.handwritten_progress_bar.set_text(f"Progress: {percentage}%")

    def _on_handwritten_complete(self, success: bool, status_text: str):
        self.is_running_handwritten = False
        self.handwritten_progress_bar.hide()
        if hasattr(self.parent_window, "notebook"):
            self.parent_window.notebook.set_show_tabs(True)

        self.btn_generate.set_sensitive(True)
        self.btn_select_images.set_sensitive(True)
        self.handwritten_status_label.set_text(status_text)
        self.selected_images = []
        self.lbl_handwritten_count.set_text("0 images selected")

        if success:
            DialogUtils.show_info(self.parent_window, "Process Completed", status_text)
        else:
            DialogUtils.show_error(self.parent_window, "Processing Error", status_text)
