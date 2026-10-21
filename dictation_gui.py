#!/usr/bin/env python3
"""Native macOS Graphical Interface for Voice Dictation & AI Study Notes (Tkinter).

Provides a clean, responsive desktop UI for voice dictation, MP3 compression,
Whisper transcription, and AI notes generation.
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime, timedelta

# Auto-inject virtual environment site-packages and bin directory
_proj_root = os.path.dirname(os.path.abspath(__file__))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

_venv_bin = os.path.join(_proj_root, ".venv", "bin")
if os.path.isdir(_venv_bin) and _venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _venv_bin + os.pathsep + os.environ.get("PATH", "")

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import config
from audio_recorder import AudioRecorder
from pipeline.dictation_notes import VoiceDictationNotesGenerator

logger = logging.getLogger("DictationGUI")


class DictationApp(tk.Tk):
    """Main window for macOS Dictation application."""

    def __init__(self):
        super().__init__()
        self.title("Dictado por Voz y Apuntes EIR")
        self.geometry("540x520")
        self.minsize(480, 460)

        # State
        self.is_recording = False
        self.audio_recorder = None
        self.recording_start_time = None
        self.pause_start_time = None
        self.total_paused_duration = timedelta(0)
        self.timer_after_id = None
        self.worker_thread = None

        self._apply_style()
        self._build_ui()

    def _apply_style(self):
        self.style = ttk.Style(self)
        # Use native aqua theme on macOS
        if "aqua" in self.style.theme_names():
            self.style.theme_use("aqua")

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding="18 16 18 16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header Title
        title_label = ttk.Label(
            main_frame,
            text="🎙️ Dictado por Voz y Apuntes IA",
            font=("Helvetica", 16, "bold")
        )
        title_label.pack(pady=(0, 4))

        subtitle_label = ttk.Label(
            main_frame,
            text="Transcripción Whisper + Redacción estructurada EIR",
            font=("Helvetica", 11)
        )
        subtitle_label.pack(pady=(0, 12))

        # Direct Recording Frame
        rec_frame = ttk.LabelFrame(main_frame, text=" Grabación Directa de Dictado ", padding="12 10 12 10")
        rec_frame.pack(fill=tk.X, pady=(0, 10))

        # Timer Display
        self.timer_var = tk.StringVar(value="00:00:00")
        timer_lbl = ttk.Label(
            rec_frame,
            textvariable=self.timer_var,
            font=("Menlo", 24, "bold"),
            anchor=tk.CENTER
        )
        timer_lbl.pack(pady=(4, 10), fill=tk.X)

        # Buttons (Record, Pause, Stop)
        btn_box = ttk.Frame(rec_frame)
        btn_box.pack(fill=tk.X, pady=(0, 4))
        btn_box.columnconfigure(0, weight=1)
        btn_box.columnconfigure(1, weight=1)
        btn_box.columnconfigure(2, weight=1)

        self.btn_rec = ttk.Button(btn_box, text="🎙️ Grabar", command=self.on_rec_clicked)
        self.btn_rec.grid(row=0, column=0, padx=4, sticky="ew")

        self.btn_pause = ttk.Button(btn_box, text="⏸️ Pausar", state=tk.DISABLED, command=self.on_pause_clicked)
        self.btn_pause.grid(row=0, column=1, padx=4, sticky="ew")

        self.btn_stop = ttk.Button(btn_box, text="⏹️ Finalizar", state=tk.DISABLED, command=self.on_stop_clicked)
        self.btn_stop.grid(row=0, column=2, padx=4, sticky="ew")

        # Separator
        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # File Alternative Frame
        file_frame = ttk.LabelFrame(main_frame, text=" O Seleccionar Archivo Existente ", padding="12 10 12 10")
        file_frame.pack(fill=tk.X, pady=(0, 10))

        file_btn_box = ttk.Frame(file_frame)
        file_btn_box.pack(fill=tk.X)

        self.btn_browse = ttk.Button(
            file_btn_box,
            text="📂 Seleccionar Audio o Texto (.wav, .mp3, .txt...)",
            command=self.on_browse_clicked
        )
        self.btn_browse.pack(fill=tk.X)

        # Whisper Configuration
        config_frame = ttk.Frame(main_frame)
        config_frame.pack(fill=tk.X, pady=(0, 8))

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
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        self.status_var = tk.StringVar(value="Listo para grabar o procesar dictado.")
        self.lbl_status = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            wraplength=480,
            font=("Helvetica", 11)
        )
        self.lbl_status.pack(anchor=tk.W, pady=(0, 4))

        self.progress_bar = ttk.Progressbar(status_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 8))

        # Result Action Buttons
        self.result_box = ttk.Frame(status_frame)
        self.result_box.pack(fill=tk.X)
        self.last_result = None

        self.btn_open_md = ttk.Button(self.result_box, text="📄 Abrir Markdown", command=self.open_markdown)
        self.btn_open_docx = ttk.Button(self.result_box, text="📘 Abrir Word", command=self.open_docx)
        self.btn_open_folder = ttk.Button(self.result_box, text="📂 Abrir Carpeta", command=self.open_output_folder)

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

    def on_rec_clicked(self):
        now = datetime.now()
        out_dir = os.path.join(config.OUTPUT_DIR, "apuntes_dictados", "bruto")
        os.makedirs(out_dir, exist_ok=True)
        raw_wav_path = os.path.join(out_dir, f"{now.strftime('%Y%m%d_%H%M%S')}_dictado_grabado.wav")

        self.audio_recorder = AudioRecorder(output_path=raw_wav_path, mic_only=True)
        if not self.audio_recorder.start():
            messagebox.showerror("Error de Micrófono", "No se pudo iniciar la grabación de audio desde el micrófono.")
            return

        self.is_recording = True
        self.recording_start_time = datetime.now()
        self.pause_start_time = None
        self.total_paused_duration = timedelta(0)

        self.btn_rec.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.NORMAL, text="⏸️ Pausar")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_browse.config(state=tk.DISABLED)
        self._hide_result_buttons()

        self.status_var.set("🔴 Grabando dictado desde el micrófono...")
        self.progress_bar["value"] = 0
        self._update_timer()

    def on_pause_clicked(self):
        if not self.is_recording or not self.audio_recorder:
            return

        if self.audio_recorder.is_paused():
            self.audio_recorder.resume()
            if self.pause_start_time:
                self.total_paused_duration += (datetime.now() - self.pause_start_time)
                self.pause_start_time = None
            self.btn_pause.config(text="⏸️ Pausar")
            self.status_var.set("🔴 Grabando dictado...")
        else:
            self.audio_recorder.pause()
            self.pause_start_time = datetime.now()
            self.btn_pause.config(text="▶️ Reanudar")
            self.status_var.set("⏸️ Grabación en pausa...")

    def on_stop_clicked(self):
        if not self.is_recording or not self.audio_recorder:
            return

        self.is_recording = False
        if self.timer_after_id:
            self.after_cancel(self.timer_after_id)
            self.timer_after_id = None

        self.btn_rec.config(state=tk.DISABLED)
        self.btn_pause.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)

        self.status_var.set("⏹️ Deteniendo grabación y guardando audio...")

        recorded_path = self.audio_recorder.stop()
        self.audio_recorder = None

        if not os.path.exists(recorded_path) or os.path.getsize(recorded_path) < 1000:
            messagebox.showwarning("Aviso", "La grabación es demasiado corta o no contiene datos.")
            self._reset_ui_state()
            return

        self._start_processing_worker(recorded_path)

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
            self._start_processing_worker(file_path)

    def _start_processing_worker(self, input_file: str):
        self.btn_rec.config(state=tk.DISABLED)
        self.btn_browse.config(state=tk.DISABLED)
        self._hide_result_buttons()
        self.progress_bar["value"] = 5

        use_remote = self.remote_whisper_var.get()
        self.worker_thread = threading.Thread(
            target=self._process_worker,
            args=(input_file, use_remote),
            daemon=True
        )
        self.worker_thread.start()

    def _process_worker(self, input_file: str, use_remote: bool):
        try:
            def update_cb(msg, progress):
                self.after(0, lambda: self._update_progress_ui(msg, progress))

            generator = VoiceDictationNotesGenerator(
                use_remote_whisper=use_remote
            )
            md_path, raw_path, mp3_backup = generator.run_from_file(input_file, status_callback=update_cb)

            docx_path = md_path.replace(".md", ".docx")
            result = {
                "markdown": md_path,
                "raw_text": raw_path,
                "mp3": mp3_backup,
                "docx": docx_path if os.path.exists(docx_path) else None
            }
            self.after(0, lambda: self._on_processing_success(result))
        except Exception as e:
            logger.exception("Error during dictation processing")
            err_msg = str(e)
            self.after(0, lambda: self._on_processing_error(err_msg))

    def _update_progress_ui(self, msg: str, progress: float):
        self.status_var.set(msg)
        self.progress_bar["value"] = int(progress * 100)

    def _on_processing_success(self, result: dict):
        self.progress_bar["value"] = 100
        self.status_var.set("🎉 ¡Apuntes generados con éxito en Markdown y Word!")
        self._show_result_buttons(result)
        self._reset_ui_state()
        messagebox.showinfo(
            "Dictado Completado",
            f"¡Apuntes estructurados generados con éxito!\n\nGuardados en:\n{result['markdown']}"
        )

    def _on_processing_error(self, err_msg: str):
        self.progress_bar["value"] = 0
        self.status_var.set(f"❌ Error: {err_msg}")
        self._reset_ui_state()
        messagebox.showerror("Error en el Procesamiento", f"Ocurrió un error al procesar el dictado:\n\n{err_msg}")

    def _reset_ui_state(self):
        self.is_recording = False
        self.btn_rec.config(state=tk.NORMAL)
        self.btn_pause.config(state=tk.DISABLED, text="⏸️ Pausar")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_browse.config(state=tk.NORMAL)

    def _update_timer(self):
        if not self.is_recording:
            return

        if not (self.audio_recorder and self.audio_recorder.is_paused()):
            now = datetime.now()
            elapsed = now - self.recording_start_time - self.total_paused_duration
            secs = max(0, int(elapsed.total_seconds()))
            h = secs // 3600
            m = (secs % 3600) // 60
            s = secs % 60
            self.timer_var.set(f"{h:02d}:{m:02d}:{s:02d}")

        self.timer_after_id = self.after(500, self._update_timer)

    def open_markdown(self):
        if self.last_result and self.last_result.get("markdown"):
            self._open_file(self.last_result["markdown"])

    def open_docx(self):
        if self.last_result and self.last_result.get("docx"):
            self._open_file(self.last_result["docx"])

    def open_output_folder(self):
        out_dir = os.path.join(config.OUTPUT_DIR, "apuntes_dictados")
        self._open_file(out_dir)

    def _open_file(self, path: str):
        if not os.path.exists(path):
            return
        if sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", path], check=False)


def launch_dictation_gui():
    app = DictationApp()
    app.mainloop()


if __name__ == "__main__":
    launch_dictation_gui()
