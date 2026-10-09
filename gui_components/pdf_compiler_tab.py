import os
import logging
import threading
import subprocess

import gi
try:
    gi.require_version('Gtk', '3.0')
except ValueError:
    pass
from gi.repository import Gtk, GLib, Pango

import config
from gui_components.dialogs import DialogUtils

logger = logging.getLogger("ZoomRecorderGUI.PDFCompilerTab")


class PDFCompilerTab(Gtk.Box):
    """Tab component that compiles one or more Markdown notes into a space-optimized PDF
    using LangGraph analysis and Pydantic layout strategies."""

    def __init__(self, parent_window: Gtk.Window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent_window = parent_window

        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(15)
        self.set_margin_bottom(15)

        self.is_running = False
        self.selected_files = []
        self._build_ui()

    def _build_ui(self):
        title = Gtk.Label()
        title.set_markup("<b>Compilador PDF de Alta Densidad</b>")
        title.modify_font(Pango.FontDescription("bold 12"))
        self.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(
            label="Optimiza el espacio al máximo con LangGraph y Pydantic: ajusta tablas, "
                  "márgenes compactos y decide automáticamente orientación vertical u horizontal."
        )
        subtitle.set_line_wrap(True)
        subtitle.set_xalign(0)
        self.pack_start(subtitle, False, False, 0)

        # File Selection Frame
        frame_files = Gtk.Frame(label="Selección de Archivos Markdown (.md)")
        box_files = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box_files.set_margin_start(12)
        box_files.set_margin_end(12)
        box_files.set_margin_top(8)
        box_files.set_margin_bottom(8)
        frame_files.add(box_files)
        self.pack_start(frame_files, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.btn_select_files = Gtk.Button(label="Seleccionar Archivos .md...")
        self.btn_select_files.connect("clicked", self.on_select_files_clicked)
        btn_box.pack_start(self.btn_select_files, False, False, 0)

        self.btn_select_folder = Gtk.Button(label="Seleccionar Carpeta Completa...")
        self.btn_select_folder.connect("clicked", self.on_select_folder_clicked)
        btn_box.pack_start(self.btn_select_folder, False, False, 0)

        self.lbl_selected_summary = Gtk.Label(label="Ningún archivo seleccionado")
        self.lbl_selected_summary.set_xalign(0)
        btn_box.pack_start(self.lbl_selected_summary, True, True, 0)
        box_files.pack_start(btn_box, False, False, 0)

        # Configuration Frame
        frame_cfg = Gtk.Frame(label="Configuración de Optimización de Espacio")
        box_cfg = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box_cfg.set_margin_start(12)
        box_cfg.set_margin_end(12)
        box_cfg.set_margin_top(8)
        box_cfg.set_margin_bottom(8)
        frame_cfg.add(box_cfg)
        self.pack_start(frame_cfg, False, False, 0)

        grid_cfg = Gtk.Grid(row_spacing=8, column_spacing=15)
        box_cfg.pack_start(grid_cfg, False, False, 0)

        # Orientation Selector
        lbl_orient = Gtk.Label(label="Orientación del Papel:")
        lbl_orient.set_xalign(0)
        grid_cfg.attach(lbl_orient, 0, 0, 1, 1)

        self.combo_orient = Gtk.ComboBoxText()
        self.combo_orient.append("auto", "Automático (Evaluación Inteligente LangGraph)")
        self.combo_orient.append("portrait", "Forzar Vertical (Portrait)")
        self.combo_orient.append("landscape", "Forzar Horizontal (Landscape)")
        self.combo_orient.set_active(0)
        grid_cfg.attach(self.combo_orient, 1, 0, 1, 1)

        # Columns Selector
        lbl_cols = Gtk.Label(label="Columnas de Texto:")
        lbl_cols.set_xalign(0)
        grid_cfg.attach(lbl_cols, 0, 1, 1, 1)

        self.combo_cols = Gtk.ComboBoxText()
        self.combo_cols.append("auto", "Automático (1 col o 2 col según densidad)")
        self.combo_cols.append("1", "1 Columna")
        self.combo_cols.append("2", "2 Columnas (Ultra-compacto tipo revista/chuleta)")
        self.combo_cols.set_active(0)
        grid_cfg.attach(self.combo_cols, 1, 1, 1, 1)

        # Font Size Selector
        lbl_font = Gtk.Label(label="Tamaño de Letra:")
        lbl_font.set_xalign(0)
        grid_cfg.attach(lbl_font, 0, 2, 1, 1)

        self.combo_font = Gtk.ComboBoxText()
        self.combo_font.append("small", "Pequeña (~8.5pt - Compacto / Estudio [Recomendado])")
        self.combo_font.append("ultra_small", "Super Pequeña (~7.2pt - Ultra-compacto / Chuleta)")
        self.combo_font.append("normal", "Normal (~9.5pt - Lectura estándar)")
        self.combo_font.set_active(0)
        grid_cfg.attach(self.combo_font, 1, 2, 1, 1)

        # Action Button
        self.btn_compile = Gtk.Button(label="Generar PDF Optimizado")
        self.btn_compile.set_sensitive(False)
        self.btn_compile.get_style_context().add_class("suggested-action")
        self.btn_compile.connect("clicked", self.on_compile_clicked)
        self.pack_start(self.btn_compile, False, False, 5)

        # Progress & Status
        self.status_label = Gtk.Label(label="Listo. Selecciona uno o varios archivos .md para comenzar.")
        self.status_label.set_xalign(0)
        self.pack_start(self.status_label, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        self.progress_bar.hide()
        self.pack_start(self.progress_bar, False, False, 0)

    def on_select_files_clicked(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Seleccionar archivos Markdown",
            parent=self.parent_window,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        dialog.set_select_multiple(True)

        filter_md = Gtk.FileFilter()
        filter_md.set_name("Archivos Markdown (*.md)")
        filter_md.add_pattern("*.md")
        dialog.add_filter(filter_md)

        notes_dir = os.path.join(getattr(config, "OUTPUT_DIR", ""), "apuntes_dictados")
        if os.path.exists(notes_dir):
            dialog.set_current_folder(notes_dir)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.selected_files = dialog.get_filenames()
            self._update_files_summary()
        dialog.destroy()

    def on_select_folder_clicked(self, widget):
        dialog = Gtk.FileChooserDialog(
            title="Seleccionar carpeta con archivos Markdown",
            parent=self.parent_window,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        notes_dir = os.path.join(getattr(config, "OUTPUT_DIR", ""), "apuntes_dictados")
        if os.path.exists(notes_dir):
            dialog.set_current_folder(notes_dir)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            folder = dialog.get_filename()
            if folder and os.path.isdir(folder):
                import glob
                self.selected_files = sorted(glob.glob(os.path.join(folder, "*.md")))
                self._update_files_summary()
        dialog.destroy()

    def _update_files_summary(self):
        count = len(self.selected_files)
        if count == 0:
            self.lbl_selected_summary.set_text("Ningún archivo seleccionado")
            self.btn_compile.set_sensitive(False)
        elif count == 1:
            name = os.path.basename(self.selected_files[0])
            self.lbl_selected_summary.set_text(f"1 archivo: {name}")
            self.btn_compile.set_sensitive(True)
        else:
            self.lbl_selected_summary.set_text(f"{count} archivos seleccionados")
            self.btn_compile.set_sensitive(True)

    def on_compile_clicked(self, widget):
        if not self.selected_files or self.is_running:
            return

        self.is_running = True
        self.btn_compile.set_sensitive(False)
        self.btn_select_files.set_sensitive(False)
        self.btn_select_folder.set_sensitive(False)

        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_text("Iniciando análisis...")
        self.progress_bar.show()

        orient_id = self.combo_orient.get_active_id()
        force_orient = None if orient_id == "auto" else orient_id

        cols_id = self.combo_cols.get_active_id()
        force_cols = None if cols_id == "auto" else int(cols_id)

        font_id = self.combo_font.get_active_id()
        font_size_mode = font_id if font_id else "small"

        threading.Thread(
            target=self._compile_worker,
            args=(list(self.selected_files), force_orient, force_cols, font_size_mode),
            daemon=True
        ).start()

    def _compile_worker(
        self,
        files: list,
        force_orient: str | None,
        force_cols: int | None,
        font_size_mode: str | None = None
    ):
        def progress_cb(message: str, progress: float):
            GLib.idle_add(self._update_ui, message, progress)

        try:
            from pipeline.pdf_compiler.compiler import compile_markdowns_to_pdf
            pdf_path, strategy = compile_markdowns_to_pdf(
                md_sources=files,
                force_orientation=force_orient,
                force_columns=force_cols,
                font_size_mode=font_size_mode,
                status_callback=progress_cb
            )
            GLib.idle_add(self._on_complete, True, pdf_path, strategy)
        except Exception as e:
            logger.exception("PDF compilation failed:")
            GLib.idle_add(self._on_complete, False, str(e), None)

    def _update_ui(self, message: str, progress: float):
        self.status_label.set_text(message)
        self.progress_bar.set_fraction(progress)
        percentage = int(progress * 100)
        self.progress_bar.set_text(f"Progreso: {percentage}%")

    def _on_complete(self, success: bool, result_payload: str, strategy):
        self.is_running = False
        self.progress_bar.hide()
        self.btn_compile.set_sensitive(True)
        self.btn_select_files.set_sensitive(True)
        self.btn_select_folder.set_sensitive(True)

        if success:
            pdf_path = result_payload
            file_name = os.path.basename(pdf_path)
            orient_str = "Horizontal (Landscape)" if strategy.orientation == "landscape" else "Vertical (Portrait)"
            font_labels = {
                "normal": "Normal (~9.5pt)",
                "small": "Pequeña (~8.5pt)",
                "ultra_small": "Super Pequeña (~7.2pt)"
            }
            font_label = font_labels.get(strategy.font_size_preset, f"{strategy.font_size_pt}pt")
            status_text = (
                f"¡PDF generado con éxito!\n\n"
                f"Archivo: {file_name}\n"
                f"Orientación: {orient_str}\n"
                f"Columnas: {strategy.columns}\n"
                f"Tamaño de letra: {font_label}\n"
                f"Márgenes: {strategy.margins_mm.css_string}\n\n"
                f"Justificación IA:\n{strategy.justification}"
            )
            self.status_label.set_text(f"PDF generado: {pdf_path}")
            DialogUtils.show_info(self.parent_window, "Compilación PDF Completada", status_text)

            # Offer to open PDF
            try:
                subprocess.Popen(["xdg-open", pdf_path])
            except Exception:
                pass
        else:
            error_msg = f"Error generando PDF: {result_payload}"
            self.status_label.set_text(error_msg)
            DialogUtils.show_error(self.parent_window, "Error de Compilación PDF", error_msg)
