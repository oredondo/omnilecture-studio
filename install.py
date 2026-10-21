#!/usr/bin/env python3
"""OmniLecture Studio Unified Cross-Platform Installer (Linux & macOS).

Orchestrates:
1. Virtual environment (.venv) creation and path configuration.
2. Dependency installation via pip or uv using requirements.txt / pyproject.toml.
3. FFmpeg and system dependencies verification / setup.
4. Safe template instantiation (pipeline_config.py from example).
5. Platform-specific desktop shortcuts, system menu items, and CLI tools.
"""

import os
import sys
import shutil
import subprocess
from abc import ABC, abstractmethod


def print_step(step_num: str, message: str) -> None:
    print(f"\n[{step_num}] \033[1;34m{message}\033[0m")


def print_success(message: str) -> None:
    print(f"\033[1;32m✓ {message}\033[0m")


def print_warning(message: str) -> None:
    print(f"\033[1;33m⚠ {message}\033[0m")


def print_error(message: str) -> None:
    print(f"\033[1;31m✗ {message}\033[0m")


class BaseInstaller(ABC):
    """Abstract base installer encapsulating common workflow steps."""

    def __init__(self):
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.venv_dir = os.path.join(self.script_dir, ".venv")
        self.venv_python = (
            os.path.join(self.venv_dir, "bin", "python")
            if sys.platform != "win32"
            else os.path.join(self.venv_dir, "Scripts", "python.exe")
        )
        self.venv_pip = (
            os.path.join(self.venv_dir, "bin", "pip")
            if sys.platform != "win32"
            else os.path.join(self.venv_dir, "Scripts", "pip.exe")
        )

    def print_banner(self, platform_name: str) -> None:
        print("=" * 65)
        print(f"      OmniLecture Studio: Installer ({platform_name})      ")
        print("=" * 65)

    def ensure_virtualenv(self) -> None:
        """Creates or verifies the isolated Python virtual environment."""
        print_step("1/5", "Verifying isolated virtual environment (.venv)...")
        uv_path = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")

        if not os.path.exists(self.venv_python):
            print("  - Creating new virtual environment...")
            if os.path.exists(uv_path):
                subprocess.run([uv_path, "venv", self.venv_dir, "--python", "3.13"], check=True)
            else:
                subprocess.run([sys.executable, "-m", "venv", self.venv_dir], check=True)
            print_success(f"Virtual environment created at: {self.venv_dir}")
        else:
            print_success(f"Virtual environment detected at: {self.venv_dir}")

    def install_dependencies(self) -> None:
        """Installs dependencies from requirements.txt or pyproject.toml."""
        print_step("2/5", "Installing Python dependencies...")
        req_file = os.path.join(self.script_dir, "requirements.txt")
        uv_path = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")

        if os.path.exists(uv_path):
            print("  - Using fast package manager 'uv'...")
            cmd = [uv_path, "pip", "install", "--python", self.venv_dir, "-r", req_file]
        else:
            print("  - Using standard pip...")
            cmd = [self.venv_pip, "install", "-r", req_file]

        try:
            subprocess.run(cmd, check=True)
            print_success("Python dependencies successfully installed.")
        except subprocess.CalledProcessError as e:
            print_error(f"Failed to install dependencies: {e}")
            raise

    def setup_config_file(self) -> None:
        """Ensures pipeline_config.py exists by copying the template if absent."""
        print_step("3/5", "Configuring pipeline parameters and credentials template...")
        cfg_example = os.path.join(self.script_dir, "pipeline_config.py.example")
        cfg_file = os.path.join(self.script_dir, "pipeline_config.py")

        if not os.path.exists(cfg_file) and os.path.exists(cfg_example):
            shutil.copy(cfg_example, cfg_file)
            print_success("Created 'pipeline_config.py' from template.")
        else:
            print_success("Configuration file 'pipeline_config.py' is ready.")

        # Ensure output directories exist
        import config
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        os.makedirs(config.TEMP_DIR, exist_ok=True)
        print_success(f"Output directory initialized at: {config.OUTPUT_DIR}")

    @abstractmethod
    def verify_system_tools(self) -> bool:
        """Verifies platform-specific system prerequisites."""
        pass

    @abstractmethod
    def install_launchers(self) -> None:
        """Creates desktop launchers, menu entries, or CLI links."""
        pass

    def run(self) -> None:
        """Executes the full installation lifecycle."""
        self.ensure_virtualenv()
        if not self.verify_system_tools():
            confirm = input("\nDo you wish to continue setup anyway? (y/N): ").strip().lower()
            if confirm not in ("y", "yes", "s", "si"):
                print_error("Installation canceled by user.")
                return
        self.install_dependencies()
        self.setup_config_file()
        self.install_launchers()


class LinuxInstaller(BaseInstaller):
    """Installer implementation for Linux systems (GNOME / Ubuntu / Zorin OS)."""

    def __init__(self):
        super().__init__()
        self.print_banner("Linux / GNOME")

    def verify_system_tools(self) -> bool:
        print_step("System Check", "Checking Linux system dependencies...")
        missing_apt = []

        try:
            import gi
            gi.require_version('Gtk', '3.0')
            print_success("Gtk 3.0: Available")
        except (ImportError, ValueError):
            missing_apt.append("python3-gi")
            print_warning("Gtk 3.0: Missing")

        try:
            import dbus
            print_success("D-Bus: Available")
        except ImportError:
            missing_apt.append("python3-dbus")
            print_warning("D-Bus: Missing")

        ffmpeg_found = shutil.which("ffmpeg") is not None
        if ffmpeg_found:
            print_success("FFmpeg: Available")
        else:
            missing_apt.append("ffmpeg")
            print_warning("FFmpeg: Missing")

        xwininfo_found = shutil.which("xwininfo") is not None
        if xwininfo_found:
            print_success("xwininfo: Available")
        else:
            missing_apt.append("x11-utils")
            print_warning("xwininfo: Missing")

        if missing_apt:
            print_warning("System libraries are required for screen recording and UI:")
            print(f"        sudo apt update && sudo apt install {' '.join(missing_apt)}")
            return False
        return True

    def install_launchers(self) -> None:
        print_step("4/5", "Installing Desktop and system menu launchers...")

        # Copy icons to user theme directories
        icons_dir_png = os.path.expanduser("~/.local/share/icons/hicolor/256x256/apps")
        icons_dir_svg = os.path.expanduser("~/.local/share/icons/hicolor/scalable/apps")
        os.makedirs(icons_dir_png, exist_ok=True)
        os.makedirs(icons_dir_svg, exist_ok=True)

        src_png = os.path.join(self.script_dir, "assets", "icon_256.png")
        src_svg = os.path.join(self.script_dir, "assets", "icon.svg")
        if os.path.exists(src_png):
            shutil.copy(src_png, os.path.join(icons_dir_png, "zoom-screen-recorder.png"))
        if os.path.exists(src_svg):
            shutil.copy(src_svg, os.path.join(icons_dir_svg, "zoom-screen-recorder.svg"))

        desktop_dir = (
            os.path.expanduser("~/Escritorio")
            if os.path.exists(os.path.expanduser("~/Escritorio"))
            else os.path.expanduser("~/Desktop")
        )
        os.makedirs(desktop_dir, exist_ok=True)

        gui_path = os.path.join(self.script_dir, "gui.py")
        python_bin = self.venv_python if os.path.exists(self.venv_python) else sys.executable
        icon_ref = src_png if os.path.exists(src_png) else "zoom-screen-recorder"

        desktop_entry = f"""[Desktop Entry]
Name=Grabador y Apuntes EIR
Comment=Grabador de pantalla, dictados y generador de apuntes e tarjetas Anki con IA
Exec={python_bin} {gui_path}
Path={self.script_dir}
Icon={icon_ref}
Terminal=false
Type=Application
Categories=Utility;AudioVideo;Education;
StartupNotify=true
StartupWMClass=zoom-screen-recorder
"""
        desktop_launcher = os.path.join(desktop_dir, "zoom-screen-recorder.desktop")
        menu_launcher = os.path.join(os.path.expanduser("~/.local/share/applications"), "zoom-screen-recorder.desktop")
        os.makedirs(os.path.dirname(menu_launcher), exist_ok=True)

        for path in (desktop_launcher, menu_launcher):
            with open(path, "w", encoding="utf-8") as f:
                f.write(desktop_entry)
            os.chmod(path, 0o755)

        subprocess.run(["gio", "set", desktop_launcher, "metadata::trusted", "yes"], stderr=subprocess.DEVNULL)
        subprocess.run(["gtk-update-icon-cache", os.path.expanduser("~/.local/share/icons/hicolor")], stderr=subprocess.DEVNULL)
        print_success(f"Desktop launcher created: {desktop_launcher}")
        print_success(f"System menu entry created: {menu_launcher}")


class MacOSInstaller(BaseInstaller):
    """Installer implementation for macOS."""

    def __init__(self):
        super().__init__()
        self.print_banner("macOS")

    def verify_system_tools(self) -> bool:
        print_step("System Check", "Verifying macOS multimedia tools and FFmpeg...")
        # Check system ffmpeg or imageio-ffmpeg
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            print_success(f"FFmpeg found on system PATH: {ffmpeg_path}")
            return True

        # Check or setup imageio-ffmpeg symlink in .venv/bin
        ffmpeg_link = os.path.join(self.venv_dir, "bin", "ffmpeg")
        try:
            out = subprocess.check_output(
                [self.venv_python, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                text=True
            ).strip()
            if os.path.exists(out):
                if os.path.islink(ffmpeg_link) or os.path.exists(ffmpeg_link):
                    try:
                        os.remove(ffmpeg_link)
                    except OSError:
                        pass
                os.symlink(out, ffmpeg_link)
                print_success(f"FFmpeg bundled binary linked at: {ffmpeg_link}")
                return True
        except Exception as e:
            print_warning(f"Could not automatically locate imageio-ffmpeg binary: {e}")
            print_warning("Recommended: install ffmpeg via Homebrew: brew install ffmpeg")
        return True

    def install_launchers(self) -> None:
        print_step("4/5", "Installing macOS CLI command, Desktop shortcut, and service...")

        # 1. CLI symlink in ~/.local/bin
        local_bin = os.path.expanduser("~/.local/bin")
        os.makedirs(local_bin, exist_ok=True)
        cli_target = os.path.join(local_bin, "dictado")
        bin_source = os.path.join(self.script_dir, "bin", "dictado")

        if os.path.exists(bin_source):
            os.chmod(bin_source, 0o755)
            if os.path.islink(cli_target) or os.path.exists(cli_target):
                try:
                    os.remove(cli_target)
                except OSError:
                    pass
            try:
                os.symlink(bin_source, cli_target)
                print_success(f"CLI command registered: 'dictado' -> {cli_target}")
            except Exception as e:
                print_warning(f"Could not link in ~/.local/bin: {e}")

        # 2. Desktop Launcher (.command)
        desktop_dir = (
            os.path.expanduser("~/Escritorio")
            if os.path.exists(os.path.expanduser("~/Escritorio"))
            else os.path.expanduser("~/Desktop")
        )
        launcher_path = os.path.join(desktop_dir, "Dictado EIR.command")
        launcher_content = f"""#!/bin/bash
# Acceso directo al Dictado por Voz EIR (OmniLecture)
cd "{self.script_dir}"
exec "{self.venv_python}" "{self.script_dir}/dictation_gui.py"
"""
        try:
            with open(launcher_path, "w", encoding="utf-8") as f:
                f.write(launcher_content)
            os.chmod(launcher_path, 0o755)
            print_success(f"Desktop launcher created: {launcher_path}")
        except Exception as e:
            print_warning(f"Failed to create desktop shortcut: {e}")

        # 3. Optional LaunchAgent service template
        launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
        os.makedirs(launch_agents_dir, exist_ok=True)
        plist_path = os.path.join(launch_agents_dir, "com.omnilecture.dictado.plist")
        log_out = os.path.join(self.script_dir, ".temp", "dictado_daemon.log")
        log_err = os.path.join(self.script_dir, ".temp", "dictado_daemon.err")
        os.makedirs(os.path.join(self.script_dir, ".temp"), exist_ok=True)

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.omnilecture.dictado</string>
    <key>ProgramArguments</key>
    <array>
        <string>{self.venv_python}</string>
        <string>{self.script_dir}/pipeline/dictation_service.py</string>
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
    <string>{self.script_dir}</string>
</dict>
</plist>
"""
        try:
            with open(plist_path, "w", encoding="utf-8") as f:
                f.write(plist_content)
            print_success(f"LaunchAgent daemon template created at: {plist_path}")
        except Exception as e:
            print_warning(f"Could not create LaunchAgent plist: {e}")


def get_installer() -> BaseInstaller:
    """Factory creating the appropriate installer for current platform."""
    if sys.platform == "darwin":
        return MacOSInstaller()
    return LinuxInstaller()


def main() -> None:
    installer = get_installer()
    installer.run()
    print("\n" + "=" * 65)
    print_success("INSTALLATION COMPLETED SUCCESSFULLY!")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
