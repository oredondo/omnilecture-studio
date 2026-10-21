import subprocess
import shutil
import os
import logging
import config

logger = logging.getLogger(__name__)

class MediaProcessor:
    """Merges and compresses the video and audio files using FFmpeg."""
    
    def __init__(self):
        self.ffmpeg_path = shutil.which("ffmpeg")
        self.active_process = None
        
    def is_available(self) -> bool:
        """Returns True if ffmpeg is installed, False otherwise."""
        return self.ffmpeg_path is not None

    def get_duration(self, file_path: str) -> float:
        """Returns the duration of a media file in seconds using ffprobe."""
        try:
            ffprobe_path = shutil.which("ffprobe")
            if not ffprobe_path:
                return 0.0
            cmd = [
                ffprobe_path,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Error getting duration for {file_path}: {e}")
            return 0.0

    def abort(self):
        """Aborts the active FFmpeg process if it is running."""
        if self.active_process:
            logger.info("Aborting active FFmpeg process...")
            try:
                self.active_process.terminate()
                self.active_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not terminate. Killing...")
                self.active_process.kill()
            except Exception as e:
                logger.error(f"Error aborting FFmpeg: {e}")
            finally:
                self.active_process = None

    def merge_and_compress(self, video_path: str, audio_path: str, output_path: str, progress_callback=None) -> bool:
        """Merges and compresses the video and audio files into the output MP4 file."""
        if not self.is_available():
            logger.error("FFmpeg is not installed on this system. Cannot merge and compress files.")
            print("\n[ERROR] FFmpeg is not installed. Please install it by running:")
            print("        sudo apt update && sudo apt install ffmpeg\n")
            return False
            
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return False
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return False
            
        # Ensure the output directory exists
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
            
        total_duration = self.get_duration(video_path)
        if total_duration <= 0.0:
            total_duration = self.get_duration(audio_path)
        if total_duration <= 0.0:
            total_duration = 1.0 # Prevent division by zero
            
        # Build FFmpeg command with sync offset alignment if configured
        sync_offset = getattr(config, "AUDIO_SYNC_OFFSET", 0.0)
        
        cmd = [
            self.ffmpeg_path,
            "-y"
        ]
        
        # If offset is negative, delay the video (advance audio)
        if sync_offset < 0.0:
            cmd.extend(["-itsoffset", str(abs(sync_offset))])
        cmd.extend(["-i", video_path])
        
        # If offset is positive, delay the audio
        if sync_offset > 0.0:
            cmd.extend(["-itsoffset", str(sync_offset)])
        cmd.extend(["-i", audio_path])
        
        # Determine MP3 output path
        mp3_output_path = os.path.splitext(output_path)[0] + ".mp3"
        
        cmd.extend([
            # Output 1: MP4 (Video and Audio)
            "-map", "0:v",
            "-map", "1:a",
            "-filter:v", f"fps=fps={config.VIDEO_FRAMERATE}",
            "-c:v", config.VIDEO_CODEC,
            "-crf", str(config.VIDEO_CRF),
            "-preset", config.VIDEO_PRESET,
            "-tune", config.VIDEO_TUNE,
            "-c:a", config.AUDIO_CODEC,
            "-b:a", config.AUDIO_BITRATE,
            "-pix_fmt", config.VIDEO_PIX_FMT,
            "-progress", "pipe:1",
            output_path,
            
            # Output 2: MP3 (Audio only)
            "-map", "1:a",
            "-c:a", "libmp3lame",
            "-b:a", getattr(config, "AUDIO_MP3_BITRATE", "128k"),
            mp3_output_path
        ])
        
        logger.info(f"Running FFmpeg merge command: {' '.join(cmd)}")
        success = self._run_ffmpeg_command(cmd, output_path, total_duration, progress_callback=progress_callback)
        if success:
            # Clean up temporary files upon success
            try:
                os.remove(video_path)
                os.remove(audio_path)
                logger.info("Temporary recording files removed.")
            except Exception as cleanup_err:
                logger.warning(f"Failed to remove temporary files: {cleanup_err}")
            return True
        return False

    def compress_video(self, input_path: str, output_path: str, progress_callback=None) -> bool:
        """Compresses a standalone video file and extracts its audio MP3 using standard settings."""
        if not self.is_available():
            logger.error("FFmpeg is not installed on this system. Cannot compress video.")
            return False
            
        if not os.path.exists(input_path):
            logger.error(f"Input video file not found: {input_path}")
            return False
            
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
            
        total_duration = self.get_duration(input_path)
        if total_duration <= 0.0:
            total_duration = 1.0
            
        mp3_output_path = os.path.splitext(output_path)[0] + ".mp3"
        
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            # Output 1: MP4 (Video and Audio)
            "-map", "0:v",
            "-map", "0:a",
            "-filter:v", f"fps=fps={config.VIDEO_FRAMERATE}",
            "-c:v", config.VIDEO_CODEC,
            "-crf", str(config.VIDEO_CRF),
            "-preset", config.VIDEO_PRESET,
            "-tune", config.VIDEO_TUNE,
            "-c:a", config.AUDIO_CODEC,
            "-b:a", config.AUDIO_BITRATE,
            "-pix_fmt", config.VIDEO_PIX_FMT,
            "-progress", "pipe:1",
            output_path,
            # Output 2: MP3 (Audio only)
            "-map", "0:a",
            "-c:a", "libmp3lame",
            "-b:a", getattr(config, "AUDIO_MP3_BITRATE", "128k"),
            mp3_output_path
        ]
        
        return self._run_ffmpeg_command(cmd, output_path, total_duration, progress_callback=progress_callback)

    def _run_ffmpeg_command(self, cmd: list, output_path: str, total_duration: float, progress_callback=None) -> bool:
        """Executes an FFmpeg command tracking progress and handling errors safely."""
        logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
        stderr_file_path = output_path + ".ffmpeg.err"
        try:
            # Spawn FFmpeg and capture progress in real-time
            with open(stderr_file_path, "w") as stderr_file:
                self.active_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=stderr_file,
                    text=True,
                    bufsize=1
                )
                
                while True:
                    line = self.active_process.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line.startswith("out_time_us="):
                        try:
                            us = int(line.split("=")[1])
                            current_time = us / 1000000.0
                            progress = min(current_time / total_duration, 1.0)
                            if progress_callback:
                                progress_callback(progress)
                        except Exception:
                            pass
                
                # Wait for the process to complete
                self.active_process.wait()
                rc = self.active_process.returncode
                self.active_process = None
            
            # Read stderr from file if failed
            stderr = ""
            if os.path.exists(stderr_file_path):
                if rc != 0:
                    try:
                        with open(stderr_file_path, "r") as f:
                            stderr = f.read()
                    except Exception as read_err:
                        stderr = f"Could not read stderr file: {read_err}"
                try:
                    os.remove(stderr_file_path)
                except Exception:
                    pass
            
            if rc != 0:
                logger.error(f"FFmpeg failed with exit code {rc}")
                logger.error(f"FFmpeg stderr: {stderr}")
                return False
                
            logger.info(f"FFmpeg command completed successfully. Saved to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error executing FFmpeg: {e}")
            self.active_process = None
            return False
