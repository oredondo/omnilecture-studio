import os
import glob
import subprocess
import shutil
import sys
from datetime import datetime

import config
from processor import MediaProcessor

def recover_latest_recording():
    print("=========================================================")
    print("           Temporary Recordings Recovery Tool            ")
    print("=========================================================")
    
    processor = MediaProcessor()
    if not processor.is_available():
        print("[ERROR] FFmpeg is not installed on this system.")
        print("        Please install it by running: sudo apt update && sudo apt install ffmpeg")
        return
        
    # Search for temp videos
    # GNOME screencast saves to the user's Videos folder
    videos_dir_es = os.path.expanduser("~/Vídeos")
    videos_dir_en = os.path.expanduser("~/Videos")
    
    video_patterns = [
        os.path.join(videos_dir_es, "temp_zoom_video_*.webm"),
        os.path.join(videos_dir_en, "temp_zoom_video_*.webm"),
        os.path.join(config.TEMP_DIR, "temp_zoom_video_*.webm"),
        "temp_zoom_video_*.webm"
    ]
    
    video_files = []
    for pattern in video_patterns:
        video_files.extend(glob.glob(pattern))
        
    # Search for temp audios
    audio_files = glob.glob(os.path.join(config.TEMP_DIR, "temp_zoom_audio_*.ogg"))
    
    if not video_files:
        print("[INFO] No temporary video files 'temp_zoom_video_*.webm' were found.")
        return
    if not audio_files:
        print("[INFO] No temporary audio files 'temp_zoom_audio_*.ogg' were found.")
        return
        
    # Match video and audio pairs by timestamp/session ID
    import re
    def extract_session_id(path):
        m = re.search(r"temp_zoom_(?:video|audio)_(\d+)", path)
        return m.group(1) if m else None

    # Group files by session ID
    sessions = {}
    for vf in video_files:
        sid = extract_session_id(vf)
        if sid:
            sessions.setdefault(sid, {})["video"] = vf

    for af in audio_files:
        sid = extract_session_id(af)
        if sid and sid in sessions:
            sessions[sid]["audio"] = af

    matched_sessions = [(sid, data) for sid, data in sessions.items() if "video" in data and "audio" in data]

    if not matched_sessions:
        print("[INFO] No matching pairs of video and audio temporary files were found.")
        return

    # Sort matched sessions by modification time of the video file (most recent first)
    matched_sessions.sort(key=lambda s: os.path.getmtime(s[1]["video"]), reverse=True)

    latest_sid, latest_data = matched_sessions[0]
    latest_video = latest_data["video"]
    latest_audio = latest_data["audio"]

    mtime = os.path.getmtime(latest_video)
    dt_end = datetime.fromtimestamp(mtime)

    # Use session ID timestamp for start time (format: temp_zoom_..._<unix_timestamp>)
    if latest_sid and latest_sid.isdigit():
        dt_start = datetime.fromtimestamp(int(latest_sid))
    else:
        ctime = os.path.getctime(latest_video)
        dt_start = datetime.fromtimestamp(ctime)

    print(f"\nThe following matching temporary recording session [{latest_sid}] has been detected:")
    print(f"  Start: {dt_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  End:   {dt_end.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Video: {latest_video} ({os.path.getsize(latest_video):,} bytes)")
    print(f"  Audio: {latest_audio} ({os.path.getsize(latest_audio):,} bytes)")

    auto_yes = "-y" in sys.argv or "--yes" in sys.argv
    if not auto_yes:
        confirm = input("\nDo you wish to merge and compress these files now? (Y/n): ").strip().lower()
        if confirm not in ("", "y", "yes", "s", "si"):
            print("Operation canceled.")
            return

    filename = f"{dt_end.strftime(config.FILENAME_FORMAT)}.mp4"
    output_path = os.path.join(config.OUTPUT_DIR, filename)

    print(f"\n[INFO] Merging and compressing recording to: {output_path}")

    last_pct = [-1]
    def on_progress(p):
        pct = int(p * 100)
        if pct != last_pct[0] and pct % 5 == 0:
            last_pct[0] = pct
            print(f"  [ENCODING PROGRESS] {pct}% complete...")
            sys.stdout.flush()

    success = processor.merge_and_compress(latest_video, latest_audio, output_path, progress_callback=on_progress)
    if success:
        print(f"[SUCCESS] Recording recovered and saved as: {filename}")
        mp3_name = os.path.splitext(filename)[0] + ".mp3"
        print(f"[SUCCESS] Audio extracted and saved as: {mp3_name}")

        # Also create symlink with start timestamp if different
        start_filename = f"{dt_start.strftime(config.FILENAME_FORMAT)}.mp4"
        start_mp3_name = f"{dt_start.strftime(config.FILENAME_FORMAT)}.mp3"
        if start_filename != filename:
            start_output_path = os.path.join(config.OUTPUT_DIR, start_filename)
            start_mp3_path = os.path.join(config.OUTPUT_DIR, start_mp3_name)
            try:
                if not os.path.exists(start_output_path):
                    os.symlink(filename, start_output_path)
                    print(f"[INFO] Created start-time alias symlink: {start_filename} -> {filename}")
                if not os.path.exists(start_mp3_path):
                    os.symlink(mp3_name, start_mp3_path)
                    print(f"[INFO] Created start-time alias symlink: {start_mp3_name} -> {mp3_name}")
            except Exception as e:
                print(f"[WARNING] Could not create start-time symlinks: {e}")
        print("\nRecovery completed successfully!")
    else:
        print("[ERROR] FFmpeg compression failed. Check the temporary files for errors.\n")

if __name__ == "__main__":
    recover_latest_recording()

