import os
import sys
import glob

# ==============================================================================
#                  ENVIRONMENT AND PATH INITIALIZATION
# ==============================================================================

def ensure_environment() -> None:
    """Prepend project root and .venv site-packages / bin to sys.path and PATH."""
    proj_root = os.path.dirname(os.path.abspath(__file__))
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)

    venv_bin = os.path.join(proj_root, ".venv", "bin")
    if os.path.isdir(venv_bin) and venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")

    # Auto-inject project's .venv site-packages into sys.path
    venv_sites = glob.glob(os.path.join(proj_root, ".venv", "lib", "python3.*", "site-packages"))
    for sp in venv_sites:
        if sp not in sys.path:
            sys.path.insert(0, sp)


ensure_environment()
_proj_root = os.path.dirname(os.path.abspath(__file__))


# ==============================================================================
#                      GENERAL RECORDER CONFIGURATIONS
# ==============================================================================

# Application Directories
if os.path.exists("/home/cristina/Documentos/Zoom"):
    DEFAULT_OUTPUT_DIR = "/home/cristina/Documentos/Zoom"
    DEFAULT_TEMP_DIR = "/home/cristina/Documentos/grabarPantalla/.temp"
elif sys.platform == "darwin":
    DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Documents/OmniLecture")
    DEFAULT_TEMP_DIR = os.path.join(_proj_root, ".temp")
else:
    docs_base = (
        os.path.expanduser("~/Documentos")
        if os.path.exists(os.path.expanduser("~/Documentos"))
        else os.path.expanduser("~/Documents")
    )
    DEFAULT_OUTPUT_DIR = os.path.join(docs_base, "OmniLecture")
    DEFAULT_TEMP_DIR = os.path.join(_proj_root, ".temp")

OUTPUT_DIR = os.getenv("OMNILECTURE_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
TEMP_DIR = os.getenv("OMNILECTURE_TEMP_DIR", DEFAULT_TEMP_DIR)
LOG_FILE = os.path.join(OUTPUT_DIR, "zoom_recorder.log")

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
VIDEO_FRAMERATE = 10

# Audio synchronization offset in seconds
AUDIO_SYNC_OFFSET = 0.2

# Constant Rate Factor (CRF) quality control (18 to 28)
VIDEO_CRF = 24

# Video codec to use
VIDEO_CODEC = "libx264"

# Encoding speed preset
VIDEO_PRESET = "medium"

# Encoder tune profile
VIDEO_TUNE = "stillimage"

# Pixel format for the final output
VIDEO_PIX_FMT = "yuv420p"

# Audio codec to use for the final merge
AUDIO_CODEC = "aac"

# Audio bitrate
AUDIO_BITRATE = "96k"

# Audio bitrate for the standalone MP3 output file
AUDIO_MP3_BITRATE = "128k"


# ==============================================================================
#                  PIPELINE SETTINGS AND SAFE RESOLVER
# ==============================================================================

def get_pipeline_setting(key: str, default=None):
    """Safely retrieves configuration from environment variable, pipeline_config, or default."""
    env_key = f"OMNILECTURE_{key.upper()}"
    if env_key in os.environ:
        val = os.environ[env_key]
        if isinstance(default, bool):
            return val.lower() in ("true", "1", "yes")
        if isinstance(default, int):
            return int(val)
        if isinstance(default, float):
            return float(val)
        return val

    try:
        import pipeline_config
        return getattr(pipeline_config, key, default)
    except (ImportError, AttributeError):
        return default
