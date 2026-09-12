import time
import os
import sys
import glob
import logging
import signal
from datetime import datetime

# Auto-inject project's .venv site-packages into sys.path if launched with system python
_proj_root = os.path.dirname(os.path.abspath(__file__))
_venv_sites = glob.glob(os.path.join(_proj_root, ".venv", "lib", "python3.*", "site-packages"))
for _sp in _venv_sites:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import config
from detector import ZoomDetector
from video_recorder import VideoRecorder
from audio_recorder import AudioRecorder
from processor import MediaProcessor

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE)
    ]
)
logger = logging.getLogger("ZoomRecorderApp")

class ZoomRecorderApp:
    """Main application orchestrating Zoom detection, recording, and processing."""
    
    def __init__(self):
        self.detector = ZoomDetector()
        self.processor = MediaProcessor()
        self.video_recorder = None
        self.audio_recorder = None
        self.is_running = True
        self.is_recording = False
        
        # Verify if FFmpeg is available
        if not self.processor.is_available():
            logger.warning("FFmpeg is not installed. Compression and merging will fail unless it is installed.")
            print("[WARNING] FFmpeg is not installed. The script will function but will not be able to perform")
            print("          the final compression until you install it by running: sudo apt install ffmpeg\n")
            
        # Register signal handlers for graceful exit
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)
        
    def _handle_exit(self, signum, frame):
        """Handles exit signals (Ctrl+C, kill) gracefully."""
        logger.info(f"Received exit signal ({signal.Signals(signum).name}). Cleaning up...")
        self.is_running = False
        if self.is_recording:
            self.stop_recording_and_process()
        sys.exit(0)

    def start_recording(self):
        """Starts both audio and video recording."""
        if self.is_recording:
            return True
            
        logger.info("Initializing recorders...")
        
        # Temporary file templates
        video_temp_template = f"temp_zoom_video_{int(time.time())}"
        audio_temp_path = os.path.join(config.TEMP_DIR, f"temp_zoom_audio_{int(time.time())}.ogg")
        
        try:
            self.video_recorder = VideoRecorder(filename_template=video_temp_template)
            self.audio_recorder = AudioRecorder(output_path=audio_temp_path)
            
            # Start recording video first
            if not self.video_recorder.start():
                logger.error("Failed to start video recording.")
                return False
                
            # Start recording audio
            if not self.audio_recorder.start():
                logger.error("Failed to start audio recording. Stopping video...")
                self.video_recorder.stop()
                return False
                
            self.is_recording = True
            logger.info("Recording started successfully. Capturing screen and audio...")
            return True
            
        except Exception as e:
            logger.error(f"Error starting recording session: {e}")
            return False

    def stop_recording_and_process(self):
        """Stops the recorders and processes the final file."""
        if not self.is_recording:
            return
            
        logger.info("Stopping recording session...")
        self.is_recording = False
        
        video_file = None
        audio_file = None
        
        # Stop recorders
        if self.video_recorder:
            video_file = self.video_recorder.stop()
        if self.audio_recorder:
            audio_file = self.audio_recorder.stop()
            
        logger.info("Recording stopped. Preparing files for post-processing...")
        
        # Wait a brief moment to ensure files are fully written and closed
        time.sleep(2.0)
        
        if not video_file or not os.path.exists(video_file):
            logger.error(f"Recorded video file not found or invalid: {video_file}")
            return
        if not audio_file or not os.path.exists(audio_file):
            logger.error(f"Recorded audio file not found or invalid: {audio_file}")
            return
            
        # Generate final file name based on date and time
        now = datetime.now()
        filename = f"{now.strftime(config.FILENAME_FORMAT)}.mp4"
        output_path = os.path.join(config.OUTPUT_DIR, filename)
        
        logger.info(f"Merging and compressing into: {output_path}")
        print(f"\n[INFO] Processing and compressing the recording. Saving to: {output_path}...")
        
        # Run merging and compression
        success = self.processor.merge_and_compress(video_file, audio_file, output_path)
        if success:
            logger.info(f"Finished processing. Final file: {output_path}")
            print(f"[SUCCESS] Recording completed and saved as: {filename}\n")
        else:
            logger.error("Failed to process the final file.")
            print("[ERROR] Failed to process the recording. Temporary files are preserved in their locations.\n")

    def run_manual_mode(self):
        """Runs the manual recording mode."""
        print("\n[INFO] Starting manual full screen recording...")
        if not self.start_recording():
            print("[ERROR] Failed to start manual recording.")
            return
            
        print("\n=========================================================")
        print("   RECORDING SCREEN AND AUDIO IN MANUAL MODE...          ")
        print("   Press ENTER to stop recording and save.               ")
        print("=========================================================")
        
        try:
            # Wait for Enter key
            input()
        except (KeyboardInterrupt, SystemExit):
            pass # Graceful shutdown handled by _handle_exit signal handler
            
        print("\n[INFO] Stopping manual recording and processing...")
        self.stop_recording_and_process()

    def run_auto_mode(self):
        """Runs the automatic Zoom detection recording mode (Daemon)."""
        print("\nWaiting for a Zoom call to start... (Ctrl+C to exit)")
        logger.info("Daemon started. Polling for Zoom calls...")
        
        while self.is_running:
            try:
                meeting_active = self.detector.is_meeting_active()
                
                if meeting_active and not self.is_recording:
                    logger.info("Zoom call detected!")
                    print("\n[CALL DETECTED] Starting to record...")
                    self.start_recording()
                    
                elif not meeting_active and self.is_recording:
                    logger.info("Zoom call ended.")
                    print("\n[CALL ENDED] Stopping recording and saving file...")
                    self.stop_recording_and_process()
                    print("Waiting for a Zoom call to start... (Ctrl+C to exit)")
                    
                # Poll status based on config.py
                time.sleep(config.POLLING_INTERVAL)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(5)

    def run(self):
        """Prompts user to select mode or parses command line arguments."""
        app_title = getattr(config, "APP_TITLE", "OmniLecture Studio")
        print("=========================================================")
        print(f"       {app_title} - Screen & Audio Recorder            ")
        print("=========================================================")
        print(f"Output directory: {config.OUTPUT_DIR}")
        print("---------------------------------------------------------")
        print(" [MANDATORY LEGAL NOTICE]")
        print(" It is legally required (GDPR and privacy regulations)")
        print(" to inform all participants before starting to record")
        print(" any video call or virtual meeting.")
        print("---------------------------------------------------------")
        
        # Check command-line flags
        mode = None
        if len(sys.argv) > 1:
            arg = sys.argv[1].lower()
            if arg in ("-a", "--auto"):
                mode = "1"
            elif arg in ("-m", "--manual"):
                mode = "2"
                
        if not mode:
            print("\nSelect recording mode:")
            print("  1) Automatic recording upon detecting Zoom calls (Daemon)")
            print("  2) Manual full screen recording immediately")
            try:
                mode = input("Selection (1 or 2, default 1): ").strip()
            except (KeyboardInterrupt, SystemExit):
                print("\nExiting...")
                return
            if not mode:
                mode = "1"
                
        if mode == "2":
            self.run_manual_mode()
        else:
            self.run_auto_mode()

if __name__ == "__main__":
    app = ZoomRecorderApp()
    app.run()
