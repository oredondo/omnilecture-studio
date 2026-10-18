#!/usr/bin/env python3
"""
Compress standalone video files using the project standard FFmpeg configuration.
Outputs both compressed MP4 (10fps, libx264, crf 24, stillimage) and MP3 (128k).
"""

import argparse
import os
import sys
import time

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from processor import MediaProcessor  # noqa: E402


def compress_video_cli(input_path: str, output_path: str = None, create_aliases: bool = True):
    """Compresses an input video and extracts companion audio MP3."""
    processor = MediaProcessor()
    if not processor.is_available():
        print("[ERROR] FFmpeg is not installed on this system.")
        sys.exit(1)

    input_path = os.path.abspath(input_path)
    if not os.path.exists(input_path):
        print(f"[ERROR] Input video not found: {input_path}")
        sys.exit(1)

    input_size = os.path.getsize(input_path)
    total_duration = processor.get_duration(input_path)
    duration_str = time.strftime("%H:%M:%S", time.gmtime(total_duration))

    print("=================================================================")
    print("                 VIDEO COMPRESSION TOOL                         ")
    print("=================================================================")
    print(f"Input file:     {input_path}")
    print(f"Input size:     {input_size / (1024 * 1024):.2f} MB ({input_size:,} bytes)")
    print(f"Video duration: {duration_str} ({total_duration:.1f}s)")
    print(f"Video codec:    {config.VIDEO_CODEC} (CRF={config.VIDEO_CRF}, Preset={config.VIDEO_PRESET})")
    print(f"Framerate:      {config.VIDEO_FRAMERATE} fps (Optimized for slides/classes)")
    print(f"Audio bitrate:  AAC {config.AUDIO_BITRATE} (in MP4) / MP3 {getattr(config, 'AUDIO_MP3_BITRATE', '128k')}")
    print("=================================================================")

    if not output_path:
        base_name = os.path.basename(input_path)
        output_path = os.path.join(config.OUTPUT_DIR, base_name)

    output_path = os.path.abspath(output_path)
    out_dir = os.path.dirname(output_path)
    os.makedirs(out_dir, exist_ok=True)

    # Use temporary file names during encoding to guarantee atomicity
    base_no_ext, _ = os.path.splitext(output_path)
    temp_mp4 = f"{base_no_ext}.encoding_tmp.mp4"
    temp_mp3 = f"{base_no_ext}.encoding_tmp.mp3"
    final_mp3 = f"{base_no_ext}.mp3"

    print("\n[INFO] Starting compression...")
    print(f"  Target MP4: {output_path}")
    print(f"  Target MP3: {final_mp3}\n")

    start_time = time.time()
    last_pct = [-1]

    def on_progress(p: float):
        pct = int(p * 100)
        if pct != last_pct[0] and pct % 5 == 0:
            last_pct[0] = pct
            elapsed = time.time() - start_time
            if p > 0.01:
                eta = (elapsed / p) - elapsed
                eta_str = time.strftime("%H:%M:%S", time.gmtime(eta))
            else:
                eta_str = "--:--:--"
            print(f"  [ENCODING PROGRESS] {pct:3d}% complete | Elapsed: {int(elapsed)}s | ETA: {eta_str}")
            sys.stdout.flush()

    success = processor.compress_video(input_path, temp_mp4, progress_callback=on_progress)

    if not success:
        print("\n[ERROR] FFmpeg compression failed.")
        if os.path.exists(temp_mp4):
            try:
                os.remove(temp_mp4)
            except OSError:
                pass
        if os.path.exists(temp_mp3):
            try:
                os.remove(temp_mp3)
            except OSError:
                pass
        sys.exit(1)

    # Replace target files with the compressed versions atomically
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path):
        # In case input was the same file being overwritten
        pass
    else:
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(temp_mp4, output_path)

    if os.path.exists(final_mp3):
        os.remove(final_mp3)
    os.rename(temp_mp3, final_mp3)

    elapsed_total = time.time() - start_time
    output_size = os.path.getsize(output_path)
    mp3_size = os.path.getsize(final_mp3)
    reduction = (1.0 - (output_size / input_size)) * 100.0

    print("\n=================================================================")
    print("[SUCCESS] Video and Audio compression completed successfully!")
    print(f"  Total time elapsed:  {time.strftime('%H:%M:%S', time.gmtime(elapsed_total))}")
    print(f"  Original size:       {input_size / (1024 * 1024):.2f} MB")
    print(f"  Compressed MP4 size: {output_size / (1024 * 1024):.2f} MB ({reduction:.1f}% space saved!)")
    print(f"  Extracted MP3 size:  {mp3_size / (1024 * 1024):.2f} MB")
    print(f"  Final MP4:           {output_path}")
    print(f"  Final MP3:           {final_mp3}")

    if create_aliases and "psicosocial" in os.path.basename(output_path).lower():
        alias_mp4 = os.path.join(out_dir, "20.Psicosocial (2ª).mp4")
        alias_mp3 = os.path.join(out_dir, "20.Psicosocial (2ª).mp3")
        try:
            if not os.path.exists(alias_mp4):
                os.symlink(os.path.basename(output_path), alias_mp4)
                print(f"  Alias symlink:       {alias_mp4} -> {os.path.basename(output_path)}")
            if not os.path.exists(alias_mp3):
                os.symlink(os.path.basename(final_mp3), alias_mp3)
                print(f"  Alias symlink:       {alias_mp3} -> {os.path.basename(final_mp3)}")
        except Exception as err:
            print(f"  [WARNING] Could not create alias symlink: {err}")

    print("=================================================================\n")


def main():
    parser = argparse.ArgumentParser(description="Compress video files using standard project settings.")
    parser.add_argument("input", nargs="?", default="/home/cristina/Documentos/psicosocial segunda.mp4",
                        help="Path to input video file (default: ~/Documentos/psicosocial segunda.mp4)")
    parser.add_argument("-o", "--output", default=None,
                        help="Path to output video file (default: ~/Documentos/Zoom/<input_name>)")
    parser.add_argument("--no-alias", action="store_true",
                        help="Do not create EIR subject aliases (e.g. 20.Psicosocial (2ª).mp4)")
    args = parser.parse_args()

    compress_video_cli(args.input, args.output, create_aliases=not args.no_alias)


if __name__ == "__main__":
    main()
