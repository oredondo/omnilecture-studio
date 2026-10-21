#!/usr/bin/env python3
"""Dictation Service for macOS & Linux.

Provides a unified interface for speech-to-text dictation and AI study notes generation:
- CLI mode: Interactive terminal recorder or direct file processing.
- GUI mode: Native macOS graphical interface.
- HTTP Service mode: Local daemon for background integration.
"""

import os
import sys
import time
import json
import logging
import argparse
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

# Ensure project root is in sys.path
_proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

import config
from pipeline.dictation_notes import VoiceDictationNotesGenerator
from recorder import AudioRecorder

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("DictationService")


class DictationService:
    """Core service for audio recording, Whisper transcription, and AI notes generation."""

    def __init__(self, output_dir: str = None, use_remote_whisper: bool = None):
        self.output_dir = output_dir or os.path.join(config.OUTPUT_DIR, "apuntes_dictados")
        os.makedirs(self.output_dir, exist_ok=True)
        self.generator = VoiceDictationNotesGenerator(
            output_dir=self.output_dir,
            use_remote_whisper=use_remote_whisper
        )

    def process_file(self, file_path: str, status_cb=None) -> dict:
        """Processes an audio or text file and returns generated file paths."""
        file_path = os.path.abspath(file_path)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Archivo no encontrado: {file_path}")

        logger.info(f"Procesando archivo para dictado: {file_path}")
        md_path, raw_path, mp3_backup = self.generator.run_from_file(file_path, status_callback=status_cb)
        return {
            "success": True,
            "markdown": md_path,
            "raw_text": raw_path,
            "mp3_backup": mp3_backup,
            "docx": md_path.replace(".md", ".docx") if os.path.exists(md_path.replace(".md", ".docx")) else None
        }

    def process_text(self, text: str, status_cb=None) -> dict:
        """Generates notes directly from transcribed text."""
        md_path, raw_path = self.generator.generate_notes_from_text(text, status_callback=status_cb)
        return {
            "success": True,
            "markdown": md_path,
            "raw_text": raw_path,
            "docx": md_path.replace(".md", ".docx") if os.path.exists(md_path.replace(".md", ".docx")) else None
        }


def run_interactive_record(service: DictationService):
    """Interactive command-line recording tool."""
    now = datetime.now()
    raw_dir = os.path.join(service.output_dir, "bruto")
    os.makedirs(raw_dir, exist_ok=True)
    temp_wav = os.path.join(raw_dir, f"{now.strftime('%Y%m%d_%H%M%S')}_dictado_grabado.wav")

    recorder = AudioRecorder(output_path=temp_wav, mic_only=True)
    active_mic = recorder._get_active_input_display_name()

    print("\n" + "=" * 60)
    print("      🎙️  GRABADOR DE DICTADO POR VOZ (OMNILECTURE)")
    print("=" * 60)
    print(f" Micrófono activo: {active_mic}")
    print(f" Guardando temporal en: {temp_wav}")
    print("-" * 60)
    print(" Comandos en directo:")
    print("   [ESPACIO / p + Enter] : Pausar / Reanudar grabación")
    print("   [ENTER / q + Enter]   : Finalizar grabación y generar apuntes")
    print("=" * 60 + "\n")

    if not recorder.start():
        print("❌ Error: No se pudo iniciar el dispositivo de audio.")
        return 1

    start_time = time.time()
    paused_duration = 0.0
    pause_start = 0.0
    is_running = True

    def timer_loop():
        while is_running:
            if not recorder.is_paused():
                elapsed = time.time() - start_time - paused_duration
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                s = int(elapsed % 60)
                sys.stdout.write(f"\r 🔴 GRABANDO: {h:02d}:{m:02d}:{s:02d} | (Pausar: 'p' + Enter | Parar: Enter) ")
                sys.stdout.flush()
            else:
                sys.stdout.write(f"\r ⏸️  EN PAUSA  | (Reanudar: 'p' + Enter | Parar: Enter)                ")
                sys.stdout.flush()
            time.sleep(0.5)

    timer_thread = threading.Thread(target=timer_loop, daemon=True)
    timer_thread.start()

    while True:
        try:
            line = input().strip().lower()
            if line in ("p", "pausa"):
                if recorder.is_paused():
                    recorder.resume()
                    if pause_start > 0:
                        paused_duration += time.time() - pause_start
                        pause_start = 0.0
                else:
                    recorder.pause()
                    pause_start = time.time()
            elif line in ("", "q", "s", "stop", "fin"):
                is_running = False
                break
        except (KeyboardInterrupt, EOFError):
            is_running = False
            break

    sys.stdout.write("\n\n⏹️ Deteniendo grabación...\n")
    sys.stdout.flush()
    recorded_path = recorder.stop()

    if not os.path.exists(recorded_path) or os.path.getsize(recorded_path) < 1000:
        print("⚠️ Grabación demasiado corta o vacía. Cancelado.")
        return 0

    print(f"✅ Audio grabado guardado: {recorded_path}")
    print("⏳ Transcribiendo y generando apuntes estructurados EIR con IA...\n")

    def status_callback(msg, progress):
        pct = int(progress * 100)
        print(f" [{pct:3d}%] {msg}")

    try:
        result = service.process_file(recorded_path, status_cb=status_callback)
        print("\n" + "=" * 60)
        print("🎉 ¡APUNTES GENERADOS CON ÉXITO!")
        print("=" * 60)
        print(f" 📄 Markdown : {result['markdown']}")
        if result.get("docx"):
            print(f" 📘 Word DOCX: {result['docx']}")
        print(f" 🎵 Audio MP3: {result['mp3_backup']}")
        print("=" * 60 + "\n")

        # Open in system viewer if on macOS
        if sys.platform == "darwin":
            try:
                import subprocess
                subprocess.run(["open", "-R", result["markdown"]], check=False)
            except Exception:
                pass

        return 0
    except Exception as e:
        print(f"❌ Error durante el procesamiento: {e}")
        logger.exception("Error processing dictation")
        return 1


class DictationHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for local dictation daemon API."""

    service = None

    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/status", "/health"):
            import pipeline_config
            response = {
                "status": "online",
                "service": "OmniLecture Dictation Service",
                "platform": sys.platform,
                "output_dir": self.service.output_dir,
                "whisper_remote": getattr(pipeline_config, "USE_REMOTE_WHISPER", True),
                "model_name": getattr(pipeline_config, "MODEL_NAME", "leria:redacta")
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(response, indent=2).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(b'{"error": "Not found"}')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if parsed.path == "/process_file":
            try:
                data = json.loads(body.decode("utf-8"))
                file_path = data.get("file_path")
                if not file_path:
                    self._set_headers(400)
                    self.wfile.write(b'{"error": "Missing file_path in request"}')
                    return
                res = self.service.process_file(file_path)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif parsed.path == "/process_text":
            try:
                data = json.loads(body.decode("utf-8"))
                text = data.get("text")
                if not text:
                    self._set_headers(400)
                    self.wfile.write(b'{"error": "Missing text in request"}')
                    return
                res = self.service.process_text(text)
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode("utf-8"))
            except Exception as e:
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self._set_headers(404)
            self.wfile.write(b'{"error": "Endpoint not found"}')


def run_http_server(service: DictationService, port: int = 8765):
    """Runs a local HTTP server for dictation automation."""
    DictationHTTPHandler.service = service
    server = HTTPServer(("127.0.0.1", port), DictationHTTPHandler)
    print(f"🚀 Servicio de Dictado OmniLecture activo en http://127.0.0.1:{port}")
    print("Endpoints disponibles:")
    print("  GET  /health        : Estado del servicio")
    print("  POST /process_file  : Procesa archivo de audio/texto (JSON: {'file_path': '...'})")
    print("  POST /process_text  : Procesa texto directo (JSON: {'text': '...'})")
    print("Presiona Ctrl+C para detener el servicio.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(
        description="Servicio de Dictado por Voz y Apuntes con IA (OmniLecture)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-r", "--record",
        action="store_true",
        help="Inicia grabación interactiva desde micrófono"
    )
    group.add_argument(
        "-f", "--file",
        type=str,
        help="Procesa un archivo de audio o texto bruto (.wav, .mp3, .txt...)"
    )
    group.add_argument(
        "-g", "--gui",
        action="store_true",
        help="Abre la interfaz gráfica nativa de dictado (macOS / Tkinter)"
    )
    group.add_argument(
        "-s", "--serve",
        action="store_true",
        help="Ejecuta el servicio HTTP local en segundo plano"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Puerto para el servicio HTTP (defecto: 8765)"
    )
    parser.add_argument(
        "--local-whisper",
        action="store_true",
        help="Forzar uso de Whisper local (faster-whisper) en lugar de API remota"
    )

    args = parser.parse_args()

    use_remote = False if args.local_whisper else None
    service = DictationService(use_remote_whisper=use_remote)

    if args.gui:
        from dictation_gui import launch_dictation_gui
        launch_dictation_gui()
    elif args.file:
        def status_cb(msg, progress):
            print(f" [{int(progress * 100):3d}%] {msg}")
        res = service.process_file(args.file, status_cb=status_cb)
        print("\n¡Procesamiento finalizado!")
        print(f"Markdown: {res['markdown']}")
        if res.get('docx'):
            print(f"Word DOCX: {res['docx']}")
    elif args.serve:
        run_http_server(service, port=args.port)
    elif args.record or len(sys.argv) == 1:
        # Default behavior when run without args or with --record: interactive record
        return run_interactive_record(service)


if __name__ == "__main__":
    sys.exit(main() or 0)
