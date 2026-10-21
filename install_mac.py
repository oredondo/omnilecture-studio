#!/usr/bin/env python3
"""Installer script for OmniLecture Voice Dictation Service on macOS.

Sets up the isolated virtual environment (.venv), dependencies,
ffmpeg binary, desktop launcher, CLI commands, and optional LaunchAgent daemon.
"""

import os
import sys
import shutil
import subprocess

def print_step(num, title):
    print(f"\n[{num}] 🔹 {title}")

def main():
    print("=" * 65)
    print("      OmniLecture: Instalador de Dictado por Voz (macOS)       ")
    print("=" * 65)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(script_dir, ".venv")
    venv_python = os.path.join(venv_dir, "bin", "python")

    # Step 1: Virtual environment
    print_step("1/5", "Verificando entorno virtual aislado (.venv)...")
    uv_path = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(venv_python):
        print("  - Creando nuevo entorno virtual aislado...")
        if os.path.exists(uv_path):
            subprocess.run([uv_path, "venv", venv_dir, "--python", "3.13"], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)
        print("  - Entorno virtual creado exitosamente.")
    else:
        print(f"  - Entorno virtual detectado en: {venv_dir}")

    # Step 2: Dependencies
    print_step("2/5", "Instalando dependencias de dictado e IA...")
    pkgs = [
        "imageio-ffmpeg",
        "sounddevice",
        "numpy",
        "scipy",
        "langchain",
        "langchain-openai",
        "langgraph",
        "python-docx",
        "faster-whisper",
        "requests",
        "pytest"
    ]
    if os.path.exists(uv_path):
        subprocess.run([uv_path, "pip", "install", "--python", venv_dir] + pkgs, check=True)
    else:
        pip_path = os.path.join(venv_dir, "bin", "pip")
        subprocess.run([pip_path, "install"] + pkgs, check=True)
    print("  - Dependencias instaladas y actualizadas.")

    # Step 3: FFmpeg binary setup
    print_step("3/5", "Configurando binario FFmpeg para compresión y filtros...")
    ffmpeg_link = os.path.join(venv_dir, "bin", "ffmpeg")
    try:
        out = subprocess.check_output(
            [venv_python, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
            text=True
        ).strip()
        if os.path.exists(out):
            if os.path.islink(ffmpeg_link) or os.path.exists(ffmpeg_link):
                try:
                    os.remove(ffmpeg_link)
                except OSError:
                    pass
            os.symlink(out, ffmpeg_link)
            print(f"  - Binario FFmpeg enlazado en: {ffmpeg_link}")
    except Exception as e:
        print(f"  - [AVISO] Configuración de FFmpeg falló: {e}")

    # Step 4: Configuration files
    print_step("4/5", "Configurando archivos de parámetros y credenciales...")
    cfg_example = os.path.join(script_dir, "pipeline_config.py.example")
    cfg_file = os.path.join(script_dir, "pipeline_config.py")
    if not os.path.exists(cfg_file) and os.path.exists(cfg_example):
        shutil.copy(cfg_example, cfg_file)
        print("  - Creado 'pipeline_config.py' a partir del archivo de ejemplo.")
    else:
        print("  - Archivo 'pipeline_config.py' listo.")

    # Ensure output directories exist
    docs_base = os.path.expanduser("~/Documents")
    out_dir = os.path.join(docs_base, "OmniLecture", "apuntes_dictados")
    os.makedirs(out_dir, exist_ok=True)
    print(f"  - Directorio de apuntes generado en: {out_dir}")

    # Step 5: Launchers & Desktop Shortcuts
    print_step("5/5", "Instalando accesos directos y comandos CLI...")

    # CLI script in ~/.local/bin
    local_bin = os.path.expanduser("~/.local/bin")
    os.makedirs(local_bin, exist_ok=True)
    cli_target = os.path.join(local_bin, "dictado")
    bin_source = os.path.join(script_dir, "bin", "dictado")

    if os.path.exists(bin_source):
        os.chmod(bin_source, 0o755)
        if os.path.islink(cli_target) or os.path.exists(cli_target):
            try:
                os.remove(cli_target)
            except OSError:
                pass
        try:
            os.symlink(bin_source, cli_target)
            print(f"  - Comando terminal disponible: 'dictado' ({cli_target})")
        except Exception as e:
            print(f"  - No se pudo crear enlace simbólico en ~/.local/bin: {e}")

    # Desktop Command Launcher
    desktop_es = os.path.expanduser("~/Escritorio")
    desktop_en = os.path.expanduser("~/Desktop")
    desktop_dir = desktop_es if os.path.exists(desktop_es) else desktop_en

    launcher_content = f"""#!/bin/bash
# Acceso directo al Dictado por Voz EIR (OmniLecture)
cd "{script_dir}"
exec "{venv_python}" "{script_dir}/dictation_gui.py"
"""
    launcher_path = os.path.join(desktop_dir, "Dictado EIR.command")
    try:
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(launcher_content)
        os.chmod(launcher_path, 0o755)
        print(f"  - Creado lanzador de escritorio: {launcher_path}")
    except Exception as e:
        print(f"  - Error creando lanzador en escritorio: {e}")

    # Optional LaunchAgent service plist
    launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(launch_agents_dir, exist_ok=True)
    plist_path = os.path.join(launch_agents_dir, "com.omnilecture.dictado.plist")
    log_out = os.path.join(script_dir, ".temp", "dictado_daemon.log")
    log_err = os.path.join(script_dir, ".temp", "dictado_daemon.err")
    os.makedirs(os.path.join(script_dir, ".temp"), exist_ok=True)

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.omnilecture.dictado</string>
    <key>ProgramArguments</key>
    <array>
        <string>{venv_python}</string>
        <string>{script_dir}/pipeline/dictation_service.py</string>
        <string>--serve</string>
        <string>--port</string>
        <string>8765</string>
    </array>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>{log_out}</string>
    <key>StandardErrorPath</key>
    <string>{log_err}</string>
    <key>WorkingDirectory</key>
    <string>{script_dir}</string>
</dict>
</plist>
"""
    try:
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_content)
        print(f"  - Plantilla de servicio daemon creada en: {plist_path}")
        print("    (Para activarlo como servicio continuo: launchctl load " + plist_path + ")")
    except Exception as e:
        print(f"  - Error creando plist de servicio: {e}")

    print("\n" + "=" * 65)
    print("      🎉 ¡INSTALACIÓN COMPLETADA CON ÉXITO EN MACOS!         ")
    print("=" * 65)
    print(" Formas de utilizar el servicio de dictado:")
    print(" 1. Aplicación Gráfica (Recomendado):")
    print("    - Doble clic en 'Dictado EIR.command' en el Escritorio")
    print("    - O ejecuta: ./bin/dictado -g")
    print(" 2. Terminal interactivo (Grabar / Pausar / Parar):")
    print("    - Ejecuta: ./bin/dictado -r")
    print(" 3. Procesar archivo de audio o texto existente:")
    print("    - Ejecuta: ./bin/dictado -f /ruta/al/archivo.mp3")
    print(" 4. Servicio HTTP local (API en segundo plano):")
    print("    - Ejecuta: ./bin/dictado -s")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    main()
