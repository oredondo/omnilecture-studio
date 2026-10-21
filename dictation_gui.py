#!/usr/bin/env python3
"""Native macOS Graphical Interface for Voice Dictation, Screen/Zoom Recording & EIR Notes (Tkinter).

Provides a clean, responsive desktop UI with tabs:
1. Dictado por Voz y Apuntes IA
2. Grabador de Pantalla y Zoom
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timedelta

import config
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from recorder import (
    AudioRecorder,
    VideoRecorder,
    ZoomDetector,
    DisplayManager,
    MediaProcessor,
)
from pipeline.dictation_notes import VoiceDictationNotesGenerator

logger = logging.getLogger("DictationGUI")


class DictationApp(tk.Tk):
    """Main window for macOS OmniLecture Studio application."""

    def __init__(self):
        super().__init__()
        self.title("OmniLecture Studio - macOS")
        self.geometry("580x620")
        self.minsize(520, 560)

        # Set window / Dock icon if available
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon_256.png")
        if os.path.exists(icon_path):
            try:
                self._app_icon = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, self._app_icon)
            except Exception:
                pass

        # Recorders and managers
        self.display_manager = DisplayManager()
        self.zoom_detector = ZoomDetector()
        self.media_processor = MediaProcessor()

        # Dictation State
        self.is_dictating = False
        self.dictation_recorder = None
        self.dictation_start_time = None
        self.dictation_pause_start_time = None
        self.dictation_paused_duration = timedelta(0)
        self.dictation_timer_id = None
        self.dictation_worker_thread = None

        # Screen Recording State
        self.is_screen_recording = False
        self.screen_video_recorder = None
        self.screen_audio_recorder = None
        self.screen_start_time = None
        self.screen_timer_id = None
        self.screen_worker_thread = None
        self.auto_zoom_enabled = False
        self.auto_zoom_thread = None

        self._apply_style()
        self._build_ui()

    def _apply_style(self):
        self.style = ttk.Style(self)
        if "aqua" in self.style.theme_names():
            self.style.theme_use("aqua")

    def _build_ui(self):
        # Create Notebook (Tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Tab 1: Voice Dictation
        self.tab_dictation = ttk.Frame(self.notebook, padding="14 12 14 12")
        self.notebook.add(self.tab_dictation, text="🎙️ Dictado por Voz")
        self._build_dictation_tab(self.tab_dictation)

        # Tab 2: Screen & Zoom Recorder
        self.tab_screen = ttk.Frame(self.notebook, padding="14 12 14 12")
        self.notebook.add(self.tab_screen, text="🖥️ Grabador de Pantalla / Zoom")
        self._build_screen_tab(self.tab_screen)

    # ==========================================================================
    #                          TAB 1: DICTADO POR VOZ
    # ==========================================================================

    def _build_dictation_tab(self, parent):
        title_label = ttk.Label(
            parent,
            text="🎙️ Dictado por Voz y Apuntes IA",
            font=("Helvetica", 15, "bold")
        )
        title_label.pack(pady=(0, 2))

        subtitle_label = ttk.Label(
            parent,
            text="Transcripción Whisper + Redacción estructurada EIR",
            font=("Helvetica", 11)
        )
        subtitle_label.pack(pady=(0, 10))

        # Direct Recording Frame
        rec_frame = ttk.LabelFrame(parent, text=" Grabación Directa de Dictado ", padding="10 8 10 8")
        rec_frame.pack(fill=tk.X, pady=(0, 8))

        # Timer Display
        self.timer_var = tk.StringVar(value="00:00:00")
        timer_lbl = ttk.Label(
            rec_frame,
            textvariable=self.timer_var,
            font=("Menlo", 22, "bold"),
            anchor=tk.CENTER
        )
        timer_lbl.pack(pady=(2, 8), fill=tk.X)

        # Buttons (Record, Pause, Stop)
        btn_box = ttk.Frame(rec_frame)
        btn_box.pack(fill=tk.X, pady=(0, 4))
        btn_box.columnconfigure(0, weight=1)
        btn_box.columnconfigure(1, weight=1)
        btn_box.columnconfigure(2, weight=1)

        self.btn_rec = ttk.Button(btn_box, text="🎙️ Grabar", command=self.on_rec_clicked)
        self.btn_rec.grid(row=0, column=0, padx=3, sticky="ew")

        self.btn_pause = ttk.Button(btn_box, text="⏸️ Pausar", state=tk.DISABLED, command=self.on_pause_clicked)
        self.btn_pause.grid(row=0, column=1, padx=3, sticky="ew")

        self.btn_stop = ttk.Button(btn_box, text="⏹️ Finalizar", state=tk.DISABLED, command=self.on_stop_clicked)
        self.btn_stop.grid(row=0, column=2, padx=3, sticky="ew")

        # Separator
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # File Alternative Frame
        file_frame = ttk.LabelFrame(parent, text=" O Seleccionar Archivo Existente ", padding="10 8 10 8")
        file_frame.pack(fill=tk.X, pady=(0, 8))

        self.btn_browse = ttk.Button(
            file_frame,
            text="📂 Seleccionar Audio o Texto (.wav, .mp3, .txt...)",
            command=self.on_browse_clicked
        )
        self.btn_browse.pack(fill=tk.X)

        # Whisper Configuration
        config_frame = ttk.Frame(parent)
        config_frame.pack(fill=tk.X, pady=(0, 6))

        self.remote_whisper_var = tk.BooleanVar(value=True)
        try:
            import pipeline_config
            self.remote_whisper_var.set(getattr(pipeline_config, "USE_REMOTE_WHISPER", True))
        except Exception:
            self.remote_whisper_var.set(True)

        self.chk_remote = ttk.Checkbutton(
            config_frame,
            text="Usar Whisper Remoto (Leria API / Transcripción rápida)",
            variable=self.remote_whisper_var
        )
        self.chk_remote.pack(anchor=tk.W)

        # Status & Progress Frame
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        self.status_var = tk.StringVar(value="Listo para grabar o procesar dictado.")
        self.lbl_status = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            wraplength=480,
            font=("Helvetica", 11)
        )
        self.lbl_status.pack(anchor=tk.W, pady=(0, 4))

        self.progress_bar = ttk.Progressbar(status_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        # Result Action Buttons
        self.result_box = ttk.Frame(status_frame)
        self.result_box.pack(fill=tk.X)
        self.last_result = None

        self.btn_open_md = ttk.Button(self.result_box, text="📄 Abrir Markdown", command=self.open_markdown)
        self.btn_open_docx = ttk.Button(self.result_box, text="📘 Abrir Word", command=self.open_docx)
        self.btn_open_folder = ttk.Button(self.result_box, text="📂 Abrir Carpeta", command=self.open_output_folder)

    # Dictation actions
    def on_rec_clicked(self):
        now = datetime.now()
        out_dir = os.path.join(config.OUTPUT_DIR, "apuntes_dictados", "bruto")
        os.makedirs(out_dir, exist_ok=True)
        raw_wav_path = os.path.join(out_dir, f"{now.strftime('%Y%m%d_%H%M%S')}_dictado_grabado.wav")

        self.dictation_recorder = AudioRecorder(output_path=raw_wav_path, mic_only=True)
        if not self.dictation_recorder.start():
            messagebox.showerror("Error de Micrófono", "No se pudo iniciar la grabación de audio desde el micrófono.")
            return

        self.is_dictating = True
        self.dictation_start_time = datetime.now()
        self.dictation_pause_start_time = None
        self.dictation_paused_duration = timedelta(0)

        self.btn_rec.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.NORMAL, text="⏸️ Pausar")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_browse.config(state=tk.DISABLED)
        self._hide_result_buttons()

        self.status_var.set("🔴 Grabando dictado desde el micrófono...")
        self.progress_bar["value"] = 0
        self._update_dictation_timer()

    def on_pause_clicked(self):
        if not self.is_dictating or not self.dictation_recorder:
            return

        if self.dictation_recorder.is_paused():
            self.dictation_recorder.resume()
            if self.dictation_pause_start_time:
                self.dictation_paused_duration += (datetime.now() - self.dictation_pause_start_time)
                self.dictation_pause_start_time = None
            self.btn_pause.config(text="⏸️ Pausar")
            self.status_var.set("🔴 Grabando dictado...")
        else:
            self.dictation_recorder.pause()
            self.dictation_pause_start_time = datetime.now()
            self.btn_pause.config(text="▶️ Reanudar")
            self.status_var.set("⏸️ Grabación en pausa...")

    def on_stop_clicked(self):
        if not self.is_dictating or not self.dictation_recorder:
            return

        self.is_dictating = False
        if self.dictation_timer_id:
            self.after_cancel(self.dictation_timer_id)
            self.dictation_timer_id = None

        self.btn_rec.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)

        self.status_var.set("⏹️ Deteniendo grabación y guardando audio...")

        recorded_path = self.dictation_recorder.stop()
        self.dictation_recorder = None

        if not os.path.exists(recorded_path) or os.path.getsize(recorded_path) < 1000:
            messagebox.showwarning("Aviso", "La grabación es demasiado corta o no contiene datos.")
            self._reset_dictation_ui_state()
            return

        self._start_dictation_processing(recorded_path)

    def on_browse_clicked(self):
        file_path = filedialog.askopenfilename(
            title="Seleccionar Audio o Texto Dictado",
            filetypes=[
                ("Archivos de Audio y Texto", "*.wav *.mp3 *.flac *.ogg *.m4a *.txt"),
                ("Archivos de Audio", "*.wav *.mp3 *.flac *.ogg *.m4a"),
                ("Archivos de Texto", "*.txt"),
                ("Todos los archivos", "*.*")
            ]
        )
        if file_path:
            self._start_dictation_processing(file_path)

    def _start_dictation_processing(self, input_file: str):
        self.btn_rec.config(state=tk.DISABLED)
        self.btn_browse.config(state=tk.DISABLED)
        self._hide_result_buttons()
        self.progress_bar["value"] = 5

        use_remote = self.remote_whisper_var.get()
        self.dictation_worker_thread = threading.Thread(
            target=self._dictation_worker,
            args=(input_file, use_remote),
            daemon=True
        )
        self.dictation_worker_thread.start()

    def _dictation_worker(self, input_file: str, use_remote: bool):
        try:
            def update_cb(msg, progress):
                self.after(0, lambda: self._update_dictation_progress(msg, progress))

            generator = VoiceDictationNotesGenerator(use_remote_whisper=use_remote)
            md_path, raw_path, mp3_backup = generator.run_from_file(input_file, status_callback=update_cb)

            docx_path = md_path.replace(".md", ".docx")
            result = {
                "markdown": md_path,
                "raw_text": raw_path,
                "mp3": mp3_backup,
                "docx": docx_path if os.path.exists(docx_path) else None
            }
            self.after(0, lambda: self._on_dictation_success(result))
        except Exception as e:
            logger.exception("Error during dictation processing")
            err_msg = str(e)
            self.after(0, lambda: self._on_dictation_error(err_msg))

    def _update_dictation_progress(self, msg: str, progress: float):
        self.status_var.set(msg)
        self.progress_bar["value"] = int(progress * 100)

    def _on_dictation_success(self, result: dict):
        self.progress_bar["value"] = 100
        self.status_var.set("🎉 ¡Apuntes generados con éxito en Markdown y Word!")
        self._show_result_buttons(result)
        self._reset_dictation_ui_state()
        messagebox.showinfo(
            "Dictado Completado",
            f"¡Apuntes estructurados generados con éxito!\n\nGuardados en:\n{result['markdown']}"
        )

    def _on_dictation_error(self, err_msg: str):
        self.progress_bar["value"] = 0
        self.status_var.set(f"❌ Error: {err_msg}")
        self._reset_dictation_ui_state()
        messagebox.showerror("Error en el Procesamiento", f"Ocurrió un error al procesar el dictado:\n\n{err_msg}")

    def _reset_dictation_ui_state(self):
        self.is_dictating = False
        self.btn_rec.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.DISABLED, text="⏸️ Pausar")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_browse.config(state=tk.NORMAL)

    def _update_dictation_timer(self):
        if not self.is_dictating:
            return

        if not (self.dictation_recorder and self.dictation_recorder.is_paused()):
            now = datetime.now()
            elapsed = now - self.dictation_start_time - self.dictation_paused_duration
            secs = max(0, int(elapsed.total_seconds()))
            h = secs // 3600
            m = (secs % 3600) // 60
            s = secs % 60
            self.timer_var.set(f"{h:02d}:{m:02d}:{s:02d}")

        self.dictation_timer_id = self.after(500, self._update_dictation_timer)

    def _show_result_buttons(self, result: dict):
        self.last_result = result
        self.btn_open_md.pack(side=tk.LEFT, padx=3)
        if result.get("docx") and os.path.exists(result["docx"]):
            self.btn_open_docx.pack(side=tk.LEFT, padx=3)
        self.btn_open_folder.pack(side=tk.LEFT, padx=3)

    def _hide_result_buttons(self):
        self.btn_open_md.pack_forget()
        self.btn_open_docx.pack_forget()
        self.btn_open_folder.pack_forget()

    def open_markdown(self):
        if self.last_result and self.last_result.get("markdown"):
            self._open_file(self.last_result["markdown"])

    def open_docx(self):
        if self.last_result and self.last_result.get("docx"):
            self._open_file(self.last_result["docx"])

    def open_output_folder(self):
        out_dir = os.path.join(config.OUTPUT_DIR, "apuntes_dictados")
        self._open_file(out_dir)

    # ==========================================================================
    #                  TAB 2: GRABADOR DE PANTALLA Y ZOOM
    # ==========================================================================

    def _build_screen_tab(self, parent):
        title_label = ttk.Label(
            parent,
            text="🖥️ Grabador de Pantalla y Zoom (macOS)",
            font=("Helvetica", 15, "bold")
        )
        title_label.pack(pady=(0, 2))

        subtitle_label = ttk.Label(
            parent,
            text="Captura nativa AVFoundation + Audio del sistema/micrófono",
            font=("Helvetica", 11)
        )
        subtitle_label.pack(pady=(0, 10))

        # Controls & Settings Frame
        settings_frame = ttk.LabelFrame(parent, text=" Configuración de Grabación ", padding="10 8 10 8")
        settings_frame.pack(fill=tk.X, pady=(0, 8))

        # Monitor Selection
        mon_row = ttk.Frame(settings_frame)
        mon_row.pack(fill=tk.X, pady=3)
        ttk.Label(mon_row, text="Monitor a grabar:", width=18).pack(side=tk.LEFT)

        self.monitor_var = tk.StringVar(value="Automático (Zoom)")
        monitors = self.display_manager.get_monitors()
        monitor_options = ["Automático (Zoom)"]
        for m in monitors:
            main_tag = " [Principal]" if m.is_primary else ""
            monitor_options.append(f"{m.name} ({m.width}x{m.height}){main_tag}")

        self.cb_monitor = ttk.Combobox(mon_row, textvariable=self.monitor_var, values=monitor_options, state="readonly")
        self.cb_monitor.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Cursor & Audio Options
        opts_row = ttk.Frame(settings_frame)
        opts_row.pack(fill=tk.X, pady=3)

        self.draw_cursor_var = tk.BooleanVar(value=getattr(config, "DRAW_CURSOR", True))
        self.chk_cursor = ttk.Checkbutton(opts_row, text="Mostrar cursor del ratón", variable=self.draw_cursor_var)
        self.chk_cursor.pack(side=tk.LEFT, padx=(0, 12))

        self.record_mic_var = tk.BooleanVar(value=getattr(config, "RECORD_MICROPHONE", False))
        self.chk_mic = ttk.Checkbutton(opts_row, text="Incluir micrófono propio", variable=self.record_mic_var)
        self.chk_mic.pack(side=tk.LEFT)

        # Automatic Zoom Mode Checkbox
        auto_frame = ttk.Frame(settings_frame)
        auto_frame.pack(fill=tk.X, pady=4)

        self.auto_zoom_var = tk.BooleanVar(value=False)
        self.chk_auto_zoom = ttk.Checkbutton(
            auto_frame,
            text="🤖 Modo Automático (Iniciar/Detener al detectar reunión de Zoom)",
            variable=self.auto_zoom_var,
            command=self.on_auto_zoom_toggled
        )
        self.chk_auto_zoom.pack(anchor=tk.W)

        # Recording Live Frame
        rec_box = ttk.LabelFrame(parent, text=" Control de Grabación ", padding="10 8 10 8")
        rec_box.pack(fill=tk.X, pady=(0, 8))

        # Live Timer
        self.screen_timer_var = tk.StringVar(value="00:00:00")
        screen_timer_lbl = ttk.Label(
            rec_box,
            textvariable=self.screen_timer_var,
            font=("Menlo", 22, "bold"),
            anchor=tk.CENTER
        )
        screen_timer_lbl.pack(pady=(2, 8), fill=tk.X)

        # Action Buttons
        btn_box = ttk.Frame(rec_box)
        btn_box.pack(fill=tk.X, pady=(0, 4))
        btn_box.columnconfigure(0, weight=1)
        btn_box.columnconfigure(1, weight=1)

        self.btn_screen_start = ttk.Button(btn_box, text="▶ Iniciar Grabación", command=self.on_screen_start_clicked)
        self.btn_screen_start.grid(row=0, column=0, padx=4, sticky="ew")

        self.btn_screen_stop = ttk.Button(btn_box, text="⏹ Detener y Procesar", state=tk.DISABLED, command=self.on_screen_stop_clicked)
        self.btn_screen_stop.grid(row=0, column=1, padx=4, sticky="ew")

        # Screen Status & Progress Frame
        screen_status_frame = ttk.Frame(parent)
        screen_status_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        self.screen_status_var = tk.StringVar(value="Listo para iniciar grabación de pantalla.")
        self.lbl_screen_status = ttk.Label(
            screen_status_frame,
            textvariable=self.screen_status_var,
            wraplength=480,
            font=("Helvetica", 11)
        )
        self.lbl_screen_status.pack(anchor=tk.W, pady=(0, 4))

        self.screen_progress_bar = ttk.Progressbar(screen_status_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.screen_progress_bar.pack(fill=tk.X, pady=(0, 6))

        # Video Result Action Buttons
        self.video_result_box = ttk.Frame(screen_status_frame)
        self.video_result_box.pack(fill=tk.X)
        self.last_video_result = None

        self.btn_open_video = ttk.Button(self.video_result_box, text="🎬 Abrir Vídeo (MP4)", command=self.open_recorded_video)
        self.btn_open_video_folder = ttk.Button(self.video_result_box, text="📂 Abrir Carpeta de Grabaciones", command=self.open_video_folder)

    # Screen Recording actions
    def on_screen_start_clicked(self):
        if self.is_screen_recording:
            return

        # Verify macOS Screen Recording permission before starting
        if sys.platform == "darwin":
            from recorder.video_recorder import AVFoundationVideoBackend
            if not AVFoundationVideoBackend.check_screen_capture_permission(request_if_missing=True):
                import subprocess
                subprocess.run(
                    ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"],
                    check=False
                )
                messagebox.showwarning(
                    "Permiso de Grabación de Pantalla Requerido",
                    "macOS requiere autorizar el permiso de Grabación de Pantalla.\n\n"
                    "Se ha abierto Ajustes del Sistema > Privacidad y seguridad > Grabación de pantalla.\n"
                    "Activa el interruptor para 'OmniLecture Studio' (o tu Terminal/IDE) y vuelve a abrir la aplicación."
                )
                return

        now = int(time.time())
        video_temp = f"temp_zoom_video_{now}"
        audio_temp = os.path.join(config.TEMP_DIR, f"temp_zoom_audio_{now}.wav")

        config.RECORD_MICROPHONE = self.record_mic_var.get()
        self.screen_video_recorder = VideoRecorder(filename_template=video_temp)
        self.screen_audio_recorder = AudioRecorder(output_path=audio_temp, mic_only=False)

        # Determine target area / monitor
        selected_text = self.monitor_var.get()
        target_area = None
        if selected_text != "Automático (Zoom)":
            monitors = self.display_manager.get_monitors()
            for m in monitors:
                if m.name in selected_text:
                    target_area = m.area
                    break
        else:
            target_area = self.display_manager.get_target_area(self.zoom_detector)

        draw_cursor = self.draw_cursor_var.get()
        if not self.screen_video_recorder.start(draw_cursor=draw_cursor, area=target_area):
            messagebox.showerror(
                "Error",
                "No se pudo iniciar la grabación de vídeo de pantalla.\n"
                "Verifica los permisos de Grabación de Pantalla en Ajustes del Sistema."
            )
            return

        if not self.screen_audio_recorder.start():
            self.screen_video_recorder.stop()
            messagebox.showerror("Error", "No se pudo iniciar la grabación de audio.")
            return

        self.is_screen_recording = True
        self.screen_start_time = datetime.now()

        self.btn_screen_start.config(state=tk.DISABLED)
        self.btn_screen_stop.config(state=tk.NORMAL)
        self.cb_monitor.config(state=tk.DISABLED)
        self.chk_auto_zoom.config(state=tk.DISABLED)
        self._hide_video_result_buttons()

        self.screen_status_var.set("🔴 Grabando pantalla y audio...")
        self.screen_progress_bar["value"] = 0
        self._update_screen_timer()

    def on_screen_stop_clicked(self):
        if not self.is_screen_recording:
            return

        self.is_screen_recording = False
        if self.screen_timer_id:
            self.after_cancel(self.screen_timer_id)
            self.screen_timer_id = None

        self.btn_screen_start.config(state=tk.DISABLED)
        self.btn_screen_stop.config(state=tk.DISABLED)

        self.screen_status_var.set("⏹️ Deteniendo grabadores de vídeo y audio...")

        vid_path = self.screen_video_recorder.stop() if self.screen_video_recorder else None
        aud_path = self.screen_audio_recorder.stop() if self.screen_audio_recorder else None

        self.screen_video_recorder = None
        self.screen_audio_recorder = None

        time.sleep(0.2)
        if not vid_path or not os.path.exists(vid_path):
            messagebox.showerror("Error", "El archivo temporal de vídeo no se generó correctamente.")
            self._reset_screen_ui_state()
            return

        self._start_screen_processing(vid_path, aud_path)

    def _start_screen_processing(self, vid_path: str, aud_path: str):
        self.screen_status_var.set(
            f"⚙️ Sincronizando y comprimiendo con FFmpeg ({config.VIDEO_FRAMERATE} FPS H.264 + AAC 48kHz)..."
        )
        self.screen_progress_bar["value"] = 20

        now = datetime.now()
        out_name = f"{now.strftime(config.FILENAME_FORMAT)}.mp4"
        out_path = os.path.join(config.OUTPUT_DIR, out_name)

        def worker():
            try:
                def progress_cb(pct):
                    self.after(0, lambda: self._update_screen_progress(pct))

                success = self.media_processor.merge_and_compress(
                    vid_path, aud_path, out_path, progress_callback=progress_cb
                )
                if success:
                    self.after(0, lambda: self._on_screen_success(out_path))
                else:
                    self.after(0, lambda: self._on_screen_error("FFmpeg falló al procesar el archivo final."))
            except Exception as e:
                logger.exception("Error during screen processing")
                self.after(0, lambda: self._on_screen_error(str(e)))

        self.screen_worker_thread = threading.Thread(target=worker, daemon=True)
        self.screen_worker_thread.start()

    def _update_screen_progress(self, pct: float):
        self.screen_progress_bar["value"] = int(pct * 100)

    def _on_screen_success(self, final_mp4: str):
        self.screen_progress_bar["value"] = 100
        self.screen_status_var.set(f"🎉 Grabación finalizada y guardada: {os.path.basename(final_mp4)}")
        self._show_video_result_buttons(final_mp4)
        self._reset_screen_ui_state()
        messagebox.showinfo(
            "Grabación Completada",
            f"¡Grabación de pantalla y audio procesada con éxito!\n\nArchivo:\n{final_mp4}"
        )

    def _on_screen_error(self, err_msg: str):
        self.screen_progress_bar["value"] = 0
        self.screen_status_var.set(f"❌ Error al procesar: {err_msg}")
        self._reset_screen_ui_state()
        messagebox.showerror("Error en el Procesamiento", f"Ocurrió un error:\n\n{err_msg}")

    def _reset_screen_ui_state(self):
        self.is_screen_recording = False
        self.btn_screen_start.config(state=tk.NORMAL)
        self.btn_screen_stop.config(state=tk.DISABLED)
        self.cb_monitor.config(state="readonly")
        self.chk_auto_zoom.config(state=tk.NORMAL)

    def _update_screen_timer(self):
        if not self.is_screen_recording:
            return

        now = datetime.now()
        elapsed = now - self.screen_start_time
        secs = max(0, int(elapsed.total_seconds()))
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        self.screen_timer_var.set(f"{h:02d}:{m:02d}:{s:02d}")

        self.screen_timer_id = self.after(500, self._update_screen_timer)

    def on_auto_zoom_toggled(self):
        self.auto_zoom_enabled = self.auto_zoom_var.get()
        if self.auto_zoom_enabled:
            self.screen_status_var.set("🤖 Modo Automático activo: esperando llamada de Zoom...")
            self.btn_screen_start.config(state=tk.DISABLED)
            self.auto_zoom_thread = threading.Thread(target=self._auto_zoom_worker, daemon=True)
            self.auto_zoom_thread.start()
        else:
            self.screen_status_var.set("Modo automático desactivado.")
            self.btn_screen_start.config(state=tk.NORMAL)

    def _auto_zoom_worker(self):
        while self.auto_zoom_enabled:
            try:
                meeting_active = self.zoom_detector.is_meeting_active()
                if meeting_active and not self.is_screen_recording:
                    self.after(0, self.on_screen_start_clicked)
                elif not meeting_active and self.is_screen_recording:
                    self.after(0, self.on_screen_stop_clicked)
            except Exception as e:
                logger.debug(f"Auto zoom poll error: {e}")
            time.sleep(getattr(config, "POLLING_INTERVAL", 3))

    def _show_video_result_buttons(self, video_path: str):
        self.last_video_result = video_path
        self.btn_open_video.pack(side=tk.LEFT, padx=3)
        self.btn_open_video_folder.pack(side=tk.LEFT, padx=3)

    def _hide_video_result_buttons(self):
        self.btn_open_video.pack_forget()
        self.btn_open_video_folder.pack_forget()

    def open_recorded_video(self):
        if self.last_video_result and os.path.exists(self.last_video_result):
            self._open_file(self.last_video_result)

    def open_video_folder(self):
        self._open_file(config.OUTPUT_DIR)

    def _open_file(self, path: str):
        if not os.path.exists(path):
            return
        if sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", path], check=False)
        else:
            import subprocess
            subprocess.run(["xdg-open", path], check=False)


def launch_dictation_gui():
    app = DictationApp()
    app.mainloop()


if __name__ == "__main__":
    launch_dictation_gui()
