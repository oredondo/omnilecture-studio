import logging
import os
import sys
import time
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


class AudioRecorder:
    """Manages audio recording of speaker output and/or microphone using GStreamer (Linux)
    or sounddevice / CoreAudio (macOS)."""

    def __init__(self, output_path: str = "temp_zoom_audio.ogg", mic_only: bool = False):
        self.output_path = os.path.abspath(output_path)
        self.mic_only = mic_only
        self._pipeline = None
        self._stream = None
        self._frames = []
        self._is_recording = False
        self._is_paused = False

        if HAS_GST and Gst is not None:
            try:
                Gst.init(None)
                self._backend = "gst"
            except Exception:
                self._backend = "sounddevice" if HAS_SOUNDDEVICE else "none"
        else:
            self._backend = "sounddevice" if HAS_SOUNDDEVICE else "none"

    def _discover_devices(self):
        """Discovers active microphone and speaker monitor device names dynamically."""
        if self._backend == "gst" and Gst is not None and hasattr(Gst, "DeviceMonitor"):
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

                    # Check if it is a monitor (speaker output)
                    if device_class == "monitor" or "monitor" in node_name.lower():
                        dev_name = node_name if node_name.endswith(".monitor") else f"{node_name}.monitor"
                        monitor_device = dev_name
                        logger.info(f"Discovered speaker monitor: '{dev.get_display_name()}' ({monitor_device})")
                    # Check if it is a microphone
                    elif device_class == "sound" or media_class == "Audio/Source":
                        if "monitor" not in node_name.lower():
                            mic_device = node_name
                            logger.info(f"Discovered microphone: '{dev.get_display_name()}' ({mic_device})")

                return mic_device, monitor_device
            except Exception as e:
                logger.warning(f"Device discovery via GStreamer failed: {e}")

        # SoundDevice fallback (macOS)
        mic_name = "Micrófono predeterminado"
        if HAS_SOUNDDEVICE:
            try:
                devices = sd.query_devices()
                default_in = sd.default.device[0]
                if default_in is not None and 0 <= default_in < len(devices):
                    mic_name = devices[default_in]['name']
            except Exception:
                pass
        return mic_name, None

    def _get_active_input_display_name(self) -> str:
        """Returns the human-readable display name of the currently active default input device."""
        if sys.platform == "darwin" or self._backend != "gst":
            if HAS_SOUNDDEVICE:
                try:
                    devices = sd.query_devices()
                    default_in = sd.default.device[0]
                    if default_in is not None and 0 <= default_in < len(devices):
                        return devices[default_in]['name']
                except Exception:
                    pass
            return "Micrófono del sistema (macOS CoreAudio)"

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

    def _sd_callback(self, indata, frames, time_info, status):
        """Audio callback for sounddevice recording."""
        if self._is_recording and not self._is_paused:
            self._frames.append(indata.copy())

    def start(self) -> bool:
        """Starts the audio recording pipeline."""
        if self._is_recording:
            logger.warning("Audio recording is already in progress.")
            return True

        # Try GStreamer pipeline if on Linux or mocked
        if self._backend == "gst" and Gst is not None:
            mic, mon = self._discover_devices()
            active_mic_name = self._get_active_input_display_name()
            if self.mic_only or mic is None or config.RECORD_MICROPHONE:
                mic = "@DEFAULT_SOURCE@"
                logger.info(f"Using default active microphone source: '{mic}' ({active_mic_name})")

            if self.mic_only:
                mon = None
            elif mon is None:
                mon = "@DEFAULT_SINK@.monitor"
                logger.info(f"Using default speaker monitor fallback: '{mon}'")

            record_mic = (config.RECORD_MICROPHONE or self.mic_only) and mic is not None
            record_mon = (not self.mic_only) and mon is not None

            if not record_mic and not record_mon:
                logger.error("No audio devices found or enabled for recording.")
                return False

            is_wav = self.output_path.lower().endswith(".wav")
            enc_str = "wavenc" if is_wav else "opusenc ! oggmux"

            if record_mic and record_mon:
                logger.info("Recording both microphone and speaker audio...")
                pipeline_str = (
                    f"audiomixer name=mixer ! audioconvert ! audioresample ! {enc_str} ! filesink location=\"{self.output_path}\" "
                    f"pulsesrc device=\"{mic}\" ! volume volume=2.0 ! audioconvert ! audioresample ! queue ! mixer.sink_0 "
                    f"pulsesrc device=\"{mon}\" ! audioconvert ! audioresample ! queue ! mixer.sink_1"
                )
            elif record_mon:
                logger.info("Recording only internal speaker audio (microphone disabled)...")
                pipeline_str = (
                    f"pulsesrc device=\"{mon}\" ! audioconvert ! audioresample ! {enc_str} ! filesink location=\"{self.output_path}\""
                )
            else:
                logger.info("Recording only microphone audio (speaker monitor disabled)...")
                pipeline_str = (
                    f"pulsesrc device=\"{mic}\" ! volume volume=2.0 ! audioconvert ! audioresample ! {enc_str} ! filesink location=\"{self.output_path}\""
                )

            try:
                self._pipeline = Gst.parse_launch(pipeline_str)
                logger.info("Setting audio pipeline to PLAYING...")
                self._pipeline.set_state(Gst.State.PLAYING)
                self._is_recording = True
                self._is_paused = False
                return True
            except Exception as e:
                logger.warning(f"GStreamer pipeline failed: {e}. Attempting sounddevice fallback.")
                self._pipeline = None

        # SoundDevice Fallback (macOS / CoreAudio)
        if HAS_SOUNDDEVICE:
            try:
                logger.info("Starting audio recording via sounddevice (CoreAudio)...")
                self._frames = []
                self._stream = sd.InputStream(
                    samplerate=16000,
                    channels=1,
                    dtype='int16',
                    callback=self._sd_callback
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

        logger.error("No compatible audio recording backend available (neither GStreamer nor sounddevice).")
        return False

    def pause(self) -> bool:
        """Pauses the audio recording."""
        if not self._is_recording:
            return False
        logger.info("Pausing audio recording...")
        self._is_paused = True
        if self._pipeline and Gst:
            self._pipeline.set_state(Gst.State.PAUSED)
        return True

    def resume(self) -> bool:
        """Resumes the audio recording."""
        if not self._is_recording:
            return False
        logger.info("Resuming audio recording...")
        self._is_paused = False
        if self._pipeline and Gst:
            self._pipeline.set_state(Gst.State.PLAYING)
        return True

    def is_paused(self) -> bool:
        """Checks if recording is currently paused."""
        return getattr(self, "_is_paused", False)

    def stop(self) -> str:
        """Stops the audio recording pipeline and returns the path to the recorded audio file."""
        if not self._is_recording and not self._pipeline and not self._stream:
            logger.warning("Audio recording was not active.")
            return self.output_path

        # Handle SoundDevice stream
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
                    is_wav = self.output_path.lower().endswith(".wav")
                    target_wav = self.output_path if is_wav else os.path.splitext(self.output_path)[0] + "_temp.wav"

                    os.makedirs(os.path.dirname(os.path.abspath(target_wav)), exist_ok=True)
                    import wave
                    with wave.open(target_wav, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)  # 16-bit
                        wf.setframerate(16000)
                        wf.writeframes(data.tobytes())

                    if target_wav != self.output_path:
                        import subprocess
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", target_wav, self.output_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=True
                        )
                        if os.path.exists(target_wav):
                            os.remove(target_wav)
                    logger.info(f"Recorded audio saved to: {self.output_path}")
                except Exception as e:
                    logger.error(f"Error writing sounddevice audio file: {e}")
            self._frames = []

        # Handle GStreamer pipeline
        if self._pipeline and Gst:
            try:
                logger.info("Stopping GStreamer audio pipeline (sending EOS)...")
                self._pipeline.send_event(Gst.Event.new_eos())
                bus = self._pipeline.get_bus()
                msg = bus.timed_pop_filtered(
                    5 * Gst.SECOND,
                    Gst.MessageType.EOS | Gst.MessageType.ERROR
                )
                if msg:
                    if msg.type == Gst.MessageType.ERROR:
                        err, _ = msg.parse_error()
                        logger.error(f"GStreamer pipeline error: {err.message}")
                    else:
                        logger.info("Audio pipeline reached EOS.")
                else:
                    logger.warning("Timeout waiting for audio pipeline EOS event.")
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"Error while stopping audio pipeline: {e}")
            finally:
                self._pipeline.set_state(Gst.State.NULL)
                self._pipeline = None

        self._is_recording = False
        self._is_paused = False
        return self.output_path
