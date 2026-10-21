import os
import sys

# ==============================================================================
#                      GENERAL RECORDER CONFIGURATIONS
# ==============================================================================

# Application Directories
if os.path.exists("/home/cristina/Documentos/Zoom"):
    DEFAULT_OUTPUT_DIR = "/home/cristina/Documentos/Zoom"
    DEFAULT_TEMP_DIR = "/home/cristina/Documentos/grabarPantalla/.temp"
elif sys.platform == "darwin":
    # On macOS, the standard system directory is ~/Documents (Finder displays it as "Documentos")
    DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Documents/OmniLecture")
    DEFAULT_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".temp")
else:
    docs_base = os.path.expanduser("~/Documentos") if os.path.exists(os.path.expanduser("~/Documentos")) else os.path.expanduser("~/Documents")
    DEFAULT_OUTPUT_DIR = os.path.join(docs_base, "OmniLecture")
    DEFAULT_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".temp")

OUTPUT_DIR = os.getenv("OMNILECTURE_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
TEMP_DIR = os.getenv("OMNILECTURE_TEMP_DIR", DEFAULT_TEMP_DIR)
LOG_FILE = os.path.join(OUTPUT_DIR, "zoom_recorder.log")

# Prepend project's .venv/bin to PATH so tools like ffmpeg are immediately found
_proj_root = os.path.dirname(os.path.abspath(__file__))
_venv_bin = os.path.join(_proj_root, ".venv", "bin")
if os.path.isdir(_venv_bin) and _venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _venv_bin + os.pathsep + os.environ.get("PATH", "")

# Ensure directories exist
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
except OSError:
    OUTPUT_DIR = os.path.join(_proj_root, "output")
    TEMP_DIR = os.path.join(_proj_root, ".temp")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    LOG_FILE = os.path.join(OUTPUT_DIR, "zoom_recorder.log")

# Final file name timestamp format (e.g., 20260609_2225)
# Reference: https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior
FILENAME_FORMAT = "%Y%m%d_%H%M"

# Polling interval in seconds to check for active Zoom meetings
POLLING_INTERVAL = 3

# ==============================================================================
#                  SCREEN AND AUDIO CAPTURE CONFIGURATIONS
# ==============================================================================

# Capture and show mouse cursor in the recording
DRAW_CURSOR = True

# Record laptop microphone input
# If False, only the system internal audio (other meeting participants) will be recorded
RECORD_MICROPHONE = False

# Screen recording target on multi-monitor setups:
# 'zoom_monitor' : Record only the monitor where Zoom is located (recommended)
# 'primary_monitor' : Record only the primary monitor
# 'all_monitors' : Record all monitors combined into a single wide video canvas
RECORD_TARGET = "zoom_monitor"

# Window names to ignore during Zoom active call detection
# (Prevents capturing secondary control bars, clipboards, or empty main windows)
ZOOM_IGNORED_TITLES = {
    "zoom workplace",
    "zoom",
    "qt selection owner for zoom",
    "chromium clipboard"
}

# ==============================================================================
#                  FFMPEG COMPRESSION AND ENCODING SETTINGS
# ==============================================================================

# Output video frame rate (FPS)
# Note: 10 FPS drastically reduces file size and is perfect for slides/text sharing
VIDEO_FRAMERATE = 10

# Audio synchronization offset in seconds
# Positive values delay audio (use when audio starts too early relative to video)
# Negative values delay video (use when audio starts too late relative to video)
AUDIO_SYNC_OFFSET = 0.2


# Constant Rate Factor (CRF) quality control
# Recommended range: 18 (highest quality, larger files) to 28 (lower quality, smaller files)
VIDEO_CRF = 24

# Video codec to use
VIDEO_CODEC = "libx264"

# Encoding speed preset
# Options: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow
# 'medium' is the default and provides a great balance of speed and file size
VIDEO_PRESET = "medium"

# Encoder tune profile
# 'stillimage' optimizes H.264 compression for slides, static text, and desktop layouts
VIDEO_TUNE = "stillimage"

# Pixel format for the final output
# 'yuv420p' ensures maximum compatibility with web browsers and mobile media players
VIDEO_PIX_FMT = "yuv420p"

# Audio codec to use for the final merge
AUDIO_CODEC = "aac"

# Audio bitrate
# 96k provides clean voice quality while using minimal disk space
AUDIO_BITRATE = "96k"

# Audio bitrate for the standalone MP3 output file
# 128k is standard and provides very clear voice quality
AUDIO_MP3_BITRATE = "128k"
