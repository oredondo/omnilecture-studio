"""OmniLecture Studio - Screen, Audio, and Meeting Recorder Engine."""

from recorder.detector import ZoomDetector
from recorder.display_manager import DisplayManager, Monitor
from recorder.video_recorder import VideoRecorder
from recorder.audio_recorder import (
    AudioRecorder,
    BaseAudioBackend,
    GstAudioBackend,
    SoundDeviceAudioBackend,
    NullAudioBackend,
)
from recorder.processor import MediaProcessor

__all__ = [
    "ZoomDetector",
    "DisplayManager",
    "Monitor",
    "VideoRecorder",
    "AudioRecorder",
    "BaseAudioBackend",
    "GstAudioBackend",
    "SoundDeviceAudioBackend",
    "NullAudioBackend",
    "MediaProcessor",
]
