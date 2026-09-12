import os

# ==============================================================================
#                 STUDY DESTINATION & SPECIALTY CONFIGURATION
# ==============================================================================
# Configure the destination domain or academic specialty for your study notes.
# This guides the LLM tone, terminology, formatting, and alerts across all pipelines.
# Available presets or custom strings:
#   - "General"      : Universal study notes for university courses, high school,
#                       or technical certifications.
#   - "EIR"          : Specialized for EIR (Enfermero Interno Residente) / Nursing.
#   - "MIR"          : Specialized for MIR (Médico Interno Residente) / Medicine.
#   - "Oposiciones"  : Public administrative, justice, state examination studies.
#   - "Law"          : Legal codes, statutes, jurisprudence, and constitutional law.
#   - "Engineering"  : Computer science, mathematics, software, and engineering.
# Or enter any custom specialty name (e.g. "Psychology", "History", "Physics", etc.).
STUDY_TARGET = "General"

# Detailed description of the study domain or topic (guides LLM context & terminology):
STUDY_DOMAIN_DESCRIPTION = "University courses, competitive exams, and technical studies"

# Language configuration for AI output and voice dictations:
# Set to "Spanish" or "English" (or any other language).
# When set to "Spanish":
#   - Voice dictations and Whisper prompts recognize Spanish punctuation and commands ("punto", "coma", "abro paréntesis", etc.).
#   - Generated study notes, Markdown summaries, and Anki cards are compiled in Spanish.
# When set to "English":
#   - Voice dictations and Whisper prompts recognize English punctuation and commands ("period", "comma", "open parenthesis", etc.).
#   - Generated study notes, Markdown summaries, and Anki cards are compiled in English.
# Note: Codebase, UI architecture, logs, and comments remain strictly in English.
STUDY_LANGUAGE = "English"

# Application display names
APP_TITLE = "OmniLecture Studio"
APP_SUBTITLE = "Screen, Audio & Handwritten AI Study Suite"
STUDY_TAB_TITLE = "Class Notes"

# Filename suffix for study notes (e.g. YYYYMMDD_HHMM_notes.md)
NOTES_SUFFIX = "notes"

# ==============================================================================
#                 LEGAL RECORDING DISCLAIMER & COMPLIANCE
# ==============================================================================
# LEGAL NOTICE: Under data protection laws (GDPR / privacy regulations) and
# image rights, it is MANDATORY to expressly inform all participants before
# starting the recording of any video call (Zoom, Google Meet, Microsoft Teams,
# etc.) and obtain their prior consent where required.
RECORDING_LEGAL_DISCLAIMER = (
    "It is legally required to inform all participants before recording any video call."
)

# ==============================================================================
#                      GENERAL RECORDER CONFIGURATIONS
# ==============================================================================

# Application Directories
_DEFAULT_OUTPUT = "/home/cristina/Documentos/Zoom"
OUTPUT_DIR = _DEFAULT_OUTPUT if os.path.exists(os.path.dirname(_DEFAULT_OUTPUT)) else os.path.expanduser("~/Documents/Zoom")
_DEFAULT_TEMP = "/home/cristina/Documentos/grabarPantalla/.temp"
TEMP_DIR = _DEFAULT_TEMP if os.path.exists(os.path.dirname(_DEFAULT_TEMP)) else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".temp")
LOG_FILE = os.path.join(OUTPUT_DIR, "zoom_recorder.log")

# Ensure directories exist
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

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
