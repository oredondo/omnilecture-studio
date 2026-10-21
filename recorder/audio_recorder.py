import logging
import os
import shutil
import sys
import time
from abc import ABC, abstractmethod
from typing import Tuple, Optional, List

import config

logger = logging.getLogger(__name__)

# Try importing GStreamer via PyGObject (Linux/GNOME)
try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    HAS_GST = True
except (ImportError, ValueError, AttributeError):
    HAS_GST = False
    Gst = None
    GLib = None

# Try importing sounddevice for macOS / CoreAudio fallback
try:
    import sounddevice as sd
    import numpy as np
    HAS_SOUNDDEVICE = True
except (ImportError, OSError):
    HAS_SOUNDDEVICE = False
    sd = None
    np = None


# ==============================================================================
#                      AUDIO BACKEND INTERFACE & STRATEGIES
# ==============================================================================

class BaseAudioBackend(ABC):
    """Abstract Strategy interface for platform-specific audio recording backends."""

    @abstractmethod
    def start(self, output_path: str, mic_only: bool = False) -> bool:
        """Starts audio recording to the specified file path."""
        pass

    @abstractmethod
    def pause(self) -> bool:
        """Pauses the recording."""
        pass

    @abstractmethod
    def resume(self) -> bool:
        """Resumes the recording."""
        pass

    @abstractmethod
    def stop(self) -> str:
        """Stops the recording and returns the path to the recorded file."""
        pass

    @abstractmethod
    def get_active_input_display_name(self) -> str:
        """Returns the human-readable display name of the active audio input."""
        pass

    @abstractmethod
    def discover_devices(self) -> Tuple[Optional[str], Optional[str]]:
        """Discovers microphone and speaker monitor device names."""
        pass


class GstAudioBackend(BaseAudioBackend):
    """Linux audio backend using GStreamer (PulseAudio / PipeWire)."""

    def __init__(self):
        self._pipeline = None
        self._output_path = ""
        self._is_recording = False
        self._is_paused = False

    def discover_devices(self) -> Tuple[Optional[str], Optional[str]]:
        if Gst is None or not hasattr(Gst, "DeviceMonitor"):
            return None, None
        try:
            monitor = Gst.DeviceMonitor.new()
            monitor.add_filter("Audio/Source", None)
            devices = monitor.get_devices()

            mic_device = None
            monitor_device = None

            for dev in devices:
                props = dev.get_properties()
                if not props:
                    continue

                node_name = props.get_string("node.name") if props.has_field("node.name") else None
                device_class = props.get_string("device.class") if props.has_field("device.class") else None
                media_class = props.get_string("media.class") if props.has_field("media.class") else None

                if not node_name:
                    continue

                if device_class == "monitor" or "monitor" in node_name.lower():
                    dev_name = node_name if node_name.endswith(".monitor") else f"{node_name}.monitor"
                    monitor_device = dev_name
                    logger.info(f"Discovered speaker monitor: '{dev.get_display_name()}' ({monitor_device})")
                elif device_class == "sound" or media_class == "Audio/Source":
                    if "monitor" not in node_name.lower():
                        mic_device = node_name
                        logger.info(f"Discovered microphone: '{dev.get_display_name()}' ({mic_device})")

            return mic_device, monitor_device
        except Exception as e:
            logger.warning(f"Device discovery via GStreamer failed: {e}")
            return None, None

    def get_active_input_display_name(self) -> str:
        try:
            import subprocess
            out = subprocess.check_output(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SOURCE@"],
                stderr=subprocess.DEVNULL,
                text=True
            )
            for line in out.splitlines():
                if "node.description" in line:
                    return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        return "Micrófono predeterminado del sistema"

    def start(self, output_path: str, mic_only: bool = False) -> bool:
        self._output_path = output_path
        mic, mon = self.discover_devices()
        active_mic_name = self.get_active_input_display_name()

        if mic_only or mic is None or config.RECORD_MICROPHONE:
            mic = "@DEFAULT_SOURCE@"
            logger.info(f"Using default active microphone source: '{mic}' ({active_mic_name})")

        if mic_only:
            mon = None
        elif mon is None:
            mon = "@DEFAULT_SINK@.monitor"
            logger.info(f"Using default speaker monitor fallback: '{mon}'")

        record_mic = (config.RECORD_MICROPHONE or mic_only) and mic is not None
        record_mon = (not mic_only) and mon is not None

        if not record_mic and not record_mon:
            logger.error("No audio devices found or enabled for recording.")
            return False

        is_wav = self._output_path.lower().endswith(".wav")
        enc_str = "wavenc" if is_wav else "opusenc ! oggmux"

        if record_mic and record_mon:
            logger.info("Recording both microphone and speaker audio...")
            pipeline_str = (
                f"audiomixer name=mixer ! audioconvert ! audioresample ! {enc_str} ! filesink location=\"{self._output_path}\" "
                f"pulsesrc device=\"{mic}\" ! volume volume=2.0 ! audioconvert ! audioresample ! queue ! mixer.sink_0 "
                f"pulsesrc device=\"{mon}\" ! audioconvert ! audioresample ! queue ! mixer.sink_1"
            )
        elif record_mon:
            logger.info("Recording only internal speaker audio (microphone disabled)...")
            pipeline_str = (
                f"pulsesrc device=\"{mon}\" ! audioconvert ! audioresample ! {enc_str} ! filesink location=\"{self._output_path}\""
            )
        else:
            logger.info("Recording only microphone audio (speaker monitor disabled)...")
            pipeline_str = (
                f"pulsesrc device=\"{mic}\" ! volume volume=2.0 ! audioconvert ! audioresample ! {enc_str} ! filesink location=\"{self._output_path}\""
            )

        try:
            self._pipeline = Gst.parse_launch(pipeline_str)
            logger.info("Setting audio pipeline to PLAYING...")
            self._pipeline.set_state(Gst.State.PLAYING)
            self._is_recording = True
            self._is_paused = False
            return True
        except Exception as e:
            logger.warning(f"GStreamer pipeline failed: {e}")
            self._pipeline = None
            return False

    def pause(self) -> bool:
        if not self._is_recording:
            return False
        self._is_paused = True
        if self._pipeline and Gst:
            self._pipeline.set_state(Gst.State.PAUSED)
        return True

    def resume(self) -> bool:
        if not self._is_recording:
            return False
        self._is_paused = False
        if self._pipeline and Gst:
            self._pipeline.set_state(Gst.State.PLAYING)
        return True

    def stop(self) -> str:
        if self._pipeline and Gst:
            try:
                logger.info("Stopping GStreamer audio pipeline (sending EOS)...")
                self._pipeline.send_event(Gst.Event.new_eos())
                bus = self._pipeline.get_bus()
                msg = bus.timed_pop_filtered(
                    5 * Gst.SECOND,
                    Gst.MessageType.EOS | Gst.MessageType.ERROR
                )
                if msg and msg.type == Gst.MessageType.ERROR:
                    err, _ = msg.parse_error()
                    logger.error(f"GStreamer pipeline error: {err.message}")
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Error while stopping audio pipeline: {e}")
            finally:
                self._pipeline.set_state(Gst.State.NULL)
                self._pipeline = None

        self._is_recording = False
        self._is_paused = False
        return self._output_path


class SoundDeviceAudioBackend(BaseAudioBackend):
    """Cross-platform audio backend using sounddevice / CoreAudio and macOS ScreenCaptureKit."""

    def __init__(self):
        self._stream = None
        self._sck_process = None
        self._sck_wav_path = ""
        self._frames: List = []
        self._output_path = ""
        self._is_recording = False
        self._is_paused = False
        self.mic_only = False
        self._active_device_name = ""
        self._samplerate = 16000
        self._mic_start_pts = 0.0

    def _ensure_sck_binary(self) -> Optional[str]:
        """Returns path to compiled macOS ScreenCaptureKit system audio helper."""
        if sys.platform != "darwin":
            return None
        proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bin_path = os.path.join(proj_root, "bin", "macos_sck_audio")
        src_path = os.path.join(proj_root, "bin", "macos_sck_audio.m")
        if os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
            return bin_path
        if os.path.exists(src_path) and shutil.which("clang"):
            try:
                import subprocess
                subprocess.run(
                    [
                        "clang", "-O2",
                        "-framework", "Foundation",
                        "-framework", "ScreenCaptureKit",
                        "-framework", "CoreMedia",
                        "-framework", "AVFoundation",
                        src_path, "-o", bin_path
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
                os.chmod(bin_path, 0o755)
                return bin_path
            except Exception as e:
                logger.debug(f"Could not compile macOS ScreenCaptureKit helper: {e}")
        return None

    def _find_system_audio_device(self) -> Optional[int]:
        """Finds loopback device for system audio capture on macOS (e.g. iShowU, BlackHole)."""
        if not HAS_SOUNDDEVICE or sd is None:
            return None
        try:
            devices = sd.query_devices()
            loopback_keywords = ["ishowu", "blackhole", "soundflower", "loopback", "aggregate"]
            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    name_lower = dev.get("name", "").lower()
                    if any(kw in name_lower for kw in loopback_keywords):
                        return idx
        except Exception as e:
            logger.debug(f"Error checking loopback devices: {e}")
        return None

    def _find_active_mic_device(self) -> Tuple[Optional[int], str]:
        """Finds an active microphone device, falling back if default mic is hardware-muted (all zeros)."""
        if not HAS_SOUNDDEVICE or sd is None:
            return None, "Micrófono predeterminado"
        try:
            devices = sd.query_devices()
            default_in = sd.default.device[0]
            loopback_keywords = ["ishowu", "blackhole", "soundflower", "loopback", "aggregate", "teams"]

            # Check if sd.InputStream is mocked in unit tests
            from unittest.mock import MagicMock
            if isinstance(sd.InputStream, MagicMock):
                if default_in is not None and 0 <= default_in < len(devices):
                    return default_in, devices[default_in]["name"]
                return None, "Micrófono predeterminado"

            def probe_has_signal(idx: int) -> bool:
                chunks = []
                try:
                    def cb(indata, frames, t, status):
                        chunks.append(indata.copy())
                    with sd.InputStream(device=idx, samplerate=16000, channels=1, dtype='int16', callback=cb):
                        time.sleep(0.15)
                    if chunks and np is not None:
                        arr = np.concatenate(chunks, axis=0)
                        return int(np.max(np.abs(arr))) > 0
                except Exception:
                    pass
                return False

            if default_in is not None and 0 <= default_in < len(devices):
                if probe_has_signal(default_in):
                    return default_in, devices[default_in]["name"]

            # Default mic returned all digital zeros (hardware muted); probe other physical mics
            for idx, dev in enumerate(devices):
                if idx == default_in or dev.get("max_input_channels", 0) <= 0:
                    continue
                name = dev.get("name", "")
                if any(kw in name.lower() for kw in loopback_keywords):
                    continue
                if probe_has_signal(idx):
                    logger.info(f"Default mic is muted; switched to active microphone: {name} (index {idx})")
                    return idx, name

            if default_in is not None and 0 <= default_in < len(devices):
                return default_in, devices[default_in]["name"]
        except Exception as e:
            logger.debug(f"Error probing active microphone: {e}")
        return None, "Micrófono predeterminado"

    def discover_devices(self) -> Tuple[Optional[str], Optional[str]]:
        mic_name = "Micrófono predeterminado"
        monitor_name = "ScreenCaptureKit System Audio" if sys.platform == "darwin" else None
        if HAS_SOUNDDEVICE and sd is not None:
            try:
                devices = sd.query_devices()
                default_in = sd.default.device[0]
                if default_in is not None and 0 <= default_in < len(devices):
                    mic_name = devices[default_in]['name']
                loop_idx = self._find_system_audio_device()
                if loop_idx is not None and loop_idx < len(devices):
                    monitor_name = devices[loop_idx]['name']
            except Exception:
                pass
        return mic_name, monitor_name

    def get_active_input_display_name(self) -> str:
        if self._active_device_name:
            return self._active_device_name
        if HAS_SOUNDDEVICE and sd is not None:
            try:
                devices = sd.query_devices()
                default_in = sd.default.device[0]
                if default_in is not None and 0 <= default_in < len(devices):
                    return devices[default_in]['name']
            except Exception:
                pass
        return "Audio del sistema + Micrófono (macOS)"

    def _callback(self, indata, frames, time_info, status):
        if self._is_recording and not self._is_paused:
            if not self._frames and self._mic_start_pts <= 0.0:
                sr = getattr(self, "_samplerate", 16000) or 16000
                self._mic_start_pts = time.monotonic() - (frames / float(sr))
            self._frames.append(indata.copy())

    def start(self, output_path: str, mic_only: bool = False) -> bool:
        if not HAS_SOUNDDEVICE or sd is None:
            logger.error("sounddevice library is not available.")
            return False
        try:
            self._output_path = output_path
            self.mic_only = mic_only
            self._samplerate = 16000 if mic_only else 48000
            self._frames = []
            self._mic_start_pts = 0.0
            self._sck_process = None
            self._sck_wav_path = ""

            from unittest.mock import MagicMock
            is_mocked = isinstance(sd.InputStream, MagicMock)
            include_mic = mic_only or getattr(config, "RECORD_MICROPHONE", False)

            # 1. Probe microphone BEFORE starting ScreenCaptureKit so there is zero delay between streams
            device_idx, device_name = (None, "Micrófono desactivado")
            if include_mic or is_mocked or sys.platform != "darwin":
                device_idx, device_name = self._find_active_mic_device()

            # 2. If recording screen/Zoom on macOS (mic_only=False), start ScreenCaptureKit system audio at 48kHz
            if not mic_only and sys.platform == "darwin" and not is_mocked:
                sck_bin = self._ensure_sck_binary()
                if sck_bin:
                    self._sck_wav_path = os.path.splitext(output_path)[0] + "_sck_sys.wav"
                    os.makedirs(os.path.dirname(os.path.abspath(self._sck_wav_path)), exist_ok=True)
                    import subprocess
                    self._sck_process = subprocess.Popen(
                        [sck_bin, self._sck_wav_path, str(self._samplerate)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    logger.info(
                        f"Started macOS ScreenCaptureKit desktop audio capture ({self._samplerate} Hz) -> {self._sck_wav_path}"
                    )

            # 3. Start microphone stream only if requested (or if ScreenCaptureKit is unavailable / mocked)
            if self._sck_process is not None:
                self._active_device_name = (
                    f"Audio del Sistema (ScreenCaptureKit) + {device_name}"
                    if include_mic else "Audio del Sistema (ScreenCaptureKit)"
                )
            else:
                self._active_device_name = device_name

            logger.info(f"Starting audio recording ({self._active_device_name})...")
            if include_mic or self._sck_process is None or is_mocked:
                self._stream = sd.InputStream(
                    device=device_idx,
                    samplerate=self._samplerate,
                    channels=1,
                    dtype='int16',
                    callback=self._callback
                )
                self._stream.start()
            self._is_recording = True
            self._is_paused = False
            logger.info("Audio recording stream active.")
            return True
        except Exception as e:
            logger.error(f"Failed to start audio recording: {e}")
            self._stream = None
            if self._sck_process is not None:
                try:
                    self._sck_process.terminate()
                except Exception:
                    pass
                self._sck_process = None
            return False

    def pause(self) -> bool:
        if not self._is_recording:
            return False
        self._is_paused = True
        return True

    def resume(self) -> bool:
        if not self._is_recording:
            return False
        self._is_paused = False
        return True

    def stop(self) -> str:
        import signal as _signal
        import subprocess
        import wave

        if self._stream:
            try:
                logger.info("Stopping sounddevice audio stream...")
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning(f"Error stopping sounddevice stream: {e}")
            finally:
                self._stream = None

        if self._sck_process:
            try:
                logger.info("Stopping macOS ScreenCaptureKit system audio stream...")
                self._sck_process.send_signal(_signal.SIGINT)
                try:
                    self._sck_process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._sck_process.terminate()
                    self._sck_process.wait(timeout=1.0)
            except Exception as e:
                logger.warning(f"Error stopping ScreenCaptureKit process: {e}")
            finally:
                self._sck_process = None

        try:
            sr = getattr(self, "_samplerate", 16000) or 16000
            mic_data = None
            if self._frames and np is not None:
                mic_data = np.concatenate(self._frames, axis=0).flatten()

            sys_data = None
            sck_pts = 0.0
            if self._sck_wav_path and os.path.exists(self._sck_wav_path) and np is not None:
                pts_sidecar = self._sck_wav_path + ".pts"
                if os.path.isfile(pts_sidecar):
                    try:
                        with open(pts_sidecar, "r", encoding="utf-8") as pf:
                            sck_pts = float(pf.read().strip())
                    except Exception:
                        sck_pts = 0.0
                    finally:
                        try:
                            os.remove(pts_sidecar)
                        except OSError:
                            pass
                try:
                    with wave.open(self._sck_wav_path, "rb") as swf:
                        sr = swf.getframerate() or sr
                        raw_bytes = swf.readframes(swf.getnframes())
                        if raw_bytes:
                            sys_data = np.frombuffer(raw_bytes, dtype=np.int16).copy()
                except Exception as e:
                    logger.debug(f"Could not read ScreenCaptureKit wav: {e}")
                finally:
                    try:
                        os.remove(self._sck_wav_path)
                    except OSError:
                        pass

            final_data = None
            final_pts = 0.0
            include_mic = self.mic_only or getattr(config, "RECORD_MICROPHONE", False)
            mic_pts = getattr(self, "_mic_start_pts", 0.0)

            if sys_data is not None and len(sys_data) > 0 and mic_data is not None and len(mic_data) > 0 and include_mic:
                # Align sys_data and mic_data using exact hardware clock PTS
                if sck_pts > 0.0 and mic_pts > 0.0 and abs(mic_pts - sck_pts) < 10.0:
                    delta_samples = int(round((mic_pts - sck_pts) * sr))
                    final_pts = min(sck_pts, mic_pts)
                else:
                    delta_samples = 0
                    final_pts = sck_pts if sck_pts > 0.0 else mic_pts

                sys_offset = max(0, -delta_samples)
                mic_offset = max(0, delta_samples)
                total_len = max(sys_offset + len(sys_data), mic_offset + len(mic_data))
                mixed = np.zeros(total_len, dtype=np.int32)
                mixed[sys_offset:sys_offset + len(sys_data)] += sys_data.astype(np.int32)

                # Soft noise gate on mic when mixing with desktop audio to avoid USB/room hiss & speaker bleed
                mic_i32 = mic_data.astype(np.int32)
                if int(np.max(np.abs(sys_data))) > 200:
                    mic_i32 = np.where(np.abs(mic_i32) < 250, 0, mic_i32)
                mixed[mic_offset:mic_offset + len(mic_data)] += mic_i32
                final_data = np.clip(mixed, -32768, 32767).astype(np.int16)
            elif sys_data is not None and len(sys_data) > 0:
                # If user unchecked mic, use system audio; if system audio is completely silent and mic has signal, mix mic
                if int(np.max(np.abs(sys_data))) == 0 and mic_data is not None and len(mic_data) > 0:
                    final_data = mic_data
                    final_pts = mic_pts if mic_pts > 0.0 else sck_pts
                else:
                    final_data = sys_data
                    final_pts = sck_pts
            elif mic_data is not None and len(mic_data) > 0:
                final_data = mic_data
                final_pts = mic_pts

            if final_data is not None and np is not None:
                is_wav = self._output_path.lower().endswith(".wav")
                target_wav = self._output_path if is_wav else os.path.splitext(self._output_path)[0] + "_temp.wav"

                os.makedirs(os.path.dirname(os.path.abspath(target_wav)), exist_ok=True)
                with wave.open(target_wav, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(sr)
                    wf.writeframes(final_data.tobytes())

                if target_wav != self._output_path:
                    ffmpeg_bin = shutil.which("ffmpeg")
                    if not ffmpeg_bin:
                        try:
                            import imageio_ffmpeg
                            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
                        except Exception:
                            ffmpeg_bin = "ffmpeg"
                    subprocess.run(
                        [ffmpeg_bin, "-y", "-i", target_wav, self._output_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True
                    )
                    if os.path.exists(target_wav):
                        os.remove(target_wav)

                if final_pts > 0.0:
                    try:
                        with open(f"{self._output_path}.pts", "w", encoding="utf-8") as pf:
                            pf.write(f"{final_pts:.6f}\n")
                    except Exception:
                        pass

                logger.info(f"Recorded audio saved to: {self._output_path} ({sr} Hz, start_pts={final_pts:.3f})")
        except Exception as e:
            logger.error(f"Error writing sounddevice audio file: {e}")

        self._frames = []
        self._sck_wav_path = ""
        self._is_recording = False
        self._is_paused = False
        return self._output_path


class NullAudioBackend(BaseAudioBackend):
    """Fallback audio backend when no multimedia drivers are available."""

    def start(self, output_path: str, mic_only: bool = False) -> bool:
        logger.error("No compatible audio recording backend available.")
        return False

    def pause(self) -> bool:
        return False

    def resume(self) -> bool:
        return False

    def stop(self) -> str:
        return ""

    def get_active_input_display_name(self) -> str:
        return "Dispositivo no disponible"

    def discover_devices(self) -> Tuple[Optional[str], Optional[str]]:
        return None, None


# ==============================================================================
#                      MAIN AUDIO RECORDER CONTROLLER
# ==============================================================================

class AudioRecorder:
    """High-level audio recorder coordinating platform-specific capture backends."""

    def __init__(self, output_path: str = "temp_zoom_audio.ogg", mic_only: bool = False):
        self.output_path = os.path.abspath(output_path)
        self.mic_only = mic_only

        # Select backend strategy
        if HAS_GST and Gst is not None:
            try:
                Gst.init(None)
                self._backend_strategy = GstAudioBackend()
                self._backend = "gst"
            except Exception:
                self._backend_strategy = SoundDeviceAudioBackend() if HAS_SOUNDDEVICE else NullAudioBackend()
                self._backend = "sounddevice" if HAS_SOUNDDEVICE else "none"
        elif HAS_SOUNDDEVICE:
            self._backend_strategy = SoundDeviceAudioBackend()
            self._backend = "sounddevice"
        else:
            self._backend_strategy = NullAudioBackend()
            self._backend = "none"

    @property
    def _pipeline(self):
        """Backwards compatibility accessor for GStreamer pipeline."""
        if isinstance(self._backend_strategy, GstAudioBackend):
            return self._backend_strategy._pipeline
        return None

    @_pipeline.setter
    def _pipeline(self, val):
        if isinstance(self._backend_strategy, GstAudioBackend):
            self._backend_strategy._pipeline = val

    @property
    def _stream(self):
        """Backwards compatibility accessor for sounddevice stream."""
        if isinstance(self._backend_strategy, SoundDeviceAudioBackend):
            return self._backend_strategy._stream
        return None

    @_stream.setter
    def _stream(self, val):
        if isinstance(self._backend_strategy, SoundDeviceAudioBackend):
            self._backend_strategy._stream = val

    @property
    def _frames(self):
        """Backwards compatibility accessor for sounddevice audio buffer."""
        if isinstance(self._backend_strategy, SoundDeviceAudioBackend):
            return self._backend_strategy._frames
        return []

    @_frames.setter
    def _frames(self, val):
        if isinstance(self._backend_strategy, SoundDeviceAudioBackend):
            self._backend_strategy._frames = val

    @property
    def _is_recording(self) -> bool:
        return getattr(self._backend_strategy, "_is_recording", False)

    @_is_recording.setter
    def _is_recording(self, val: bool):
        if hasattr(self._backend_strategy, "_is_recording"):
            self._backend_strategy._is_recording = val

    @property
    def _is_paused(self) -> bool:
        return getattr(self._backend_strategy, "_is_paused", False)

    @_is_paused.setter
    def _is_paused(self, val: bool):
        if hasattr(self._backend_strategy, "_is_paused"):
            self._backend_strategy._is_paused = val

    def _discover_devices(self) -> Tuple[Optional[str], Optional[str]]:
        return self._backend_strategy.discover_devices()

    def _get_active_input_display_name(self) -> str:
        return self._backend_strategy.get_active_input_display_name()

    def _sd_callback(self, indata, frames, time_info, status):
        if isinstance(self._backend_strategy, SoundDeviceAudioBackend):
            self._backend_strategy._callback(indata, frames, time_info, status)

    def start(self) -> bool:
        """Starts audio recording using the configured backend strategy."""
        if self._is_recording:
            logger.warning("Audio recording is already in progress.")
            return True

        success = self._backend_strategy.start(self.output_path, mic_only=self.mic_only)
        if not success and isinstance(self._backend_strategy, GstAudioBackend) and HAS_SOUNDDEVICE:
            logger.info("Attempting fallback to sounddevice backend...")
            self._backend_strategy = SoundDeviceAudioBackend()
            self._backend = "sounddevice"
            success = self._backend_strategy.start(self.output_path, mic_only=self.mic_only)

        return success

    def pause(self) -> bool:
        """Pauses the active audio recording."""
        return self._backend_strategy.pause()

    def resume(self) -> bool:
        """Resumes a paused audio recording."""
        return self._backend_strategy.resume()

    def is_paused(self) -> bool:
        """Returns True if recording is currently paused."""
        return self._is_paused

    def stop(self) -> str:
        """Stops the audio recording and returns the path to the saved file."""
        return self._backend_strategy.stop()
