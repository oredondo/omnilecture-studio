import logging
import os
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
    """Cross-platform audio backend using sounddevice / CoreAudio (macOS default)."""

    def __init__(self):
        self._stream = None
        self._frames: List = []
        self._output_path = ""
        self._is_recording = False
        self._is_paused = False

    def discover_devices(self) -> Tuple[Optional[str], Optional[str]]:
        mic_name = "Micrófono predeterminado"
        if HAS_SOUNDDEVICE and sd is not None:
            try:
                devices = sd.query_devices()
                default_in = sd.default.device[0]
                if default_in is not None and 0 <= default_in < len(devices):
                    mic_name = devices[default_in]['name']
            except Exception:
                pass
        return mic_name, None

    def get_active_input_display_name(self) -> str:
        if HAS_SOUNDDEVICE and sd is not None:
            try:
                devices = sd.query_devices()
                default_in = sd.default.device[0]
                if default_in is not None and 0 <= default_in < len(devices):
                    return devices[default_in]['name']
            except Exception:
                pass
        return "Micrófono del sistema (macOS CoreAudio)"

    def _callback(self, indata, frames, time_info, status):
        if self._is_recording and not self._is_paused:
            self._frames.append(indata.copy())

    def start(self, output_path: str, mic_only: bool = False) -> bool:
        if not HAS_SOUNDDEVICE or sd is None:
            logger.error("sounddevice library is not available.")
            return False
        try:
            self._output_path = output_path
            self._frames = []
            logger.info("Starting audio recording via sounddevice (CoreAudio)...")
            self._stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype='int16',
                callback=self._callback
            )
            self._stream.start()
            self._is_recording = True
            self._is_paused = False
            logger.info("Sounddevice microphone stream active.")
            return True
        except Exception as e:
            logger.error(f"Failed to start sounddevice recording: {e}")
            self._stream = None
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
        if self._stream:
            try:
                logger.info("Stopping sounddevice audio stream...")
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning(f"Error stopping sounddevice stream: {e}")
            finally:
                self._stream = None

        if self._frames and np is not None:
            try:
                data = np.concatenate(self._frames, axis=0)
                is_wav = self._output_path.lower().endswith(".wav")
                target_wav = self._output_path if is_wav else os.path.splitext(self._output_path)[0] + "_temp.wav"

                os.makedirs(os.path.dirname(os.path.abspath(target_wav)), exist_ok=True)
                import wave
                with wave.open(target_wav, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(16000)
                    wf.writeframes(data.tobytes())

                if target_wav != self._output_path:
                    import subprocess
                    subprocess.run(
                        ["ffmpeg", "-y", "-i", target_wav, self._output_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True
                    )
                    if os.path.exists(target_wav):
                        os.remove(target_wav)
                logger.info(f"Recorded audio saved to: {self._output_path}")
            except Exception as e:
                logger.error(f"Error writing sounddevice audio file: {e}")
        self._frames = []
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
