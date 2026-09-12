import os
import logging
from datetime import datetime
import tempfile

import config
from pipeline.llm_manager import LLMManager
from pipeline.prompts import DICTATION_NOTES_PROMPT
from pipeline.transcription import AudioTranscriber

logger = logging.getLogger("VoiceDictationNotesGenerator")


class VoiceDictationNotesGenerator:
    """Orchestrator for transcribing audio dictations and generating
    structured AI study notes using remote Leria or local Whisper AI."""

    def __init__(
        self,
        output_dir: str = None,
        temperature: float = 0.0,
        use_remote_whisper: bool = None
    ):
        self.output_dir = output_dir or os.path.join(config.OUTPUT_DIR, "apuntes_dictados")
        self.raw_dir = os.path.join(self.output_dir, "bruto")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.raw_dir, exist_ok=True)
        self.temperature = temperature
        self.llm_manager = LLMManager(temperature=self.temperature)
        if use_remote_whisper is None:
            import pipeline_config
            self.use_remote_whisper = getattr(pipeline_config, "USE_REMOTE_WHISPER", True)
        else:
            self.use_remote_whisper = use_remote_whisper

    def compress_to_ultra_light_mp3(
        self,
        input_audio_path: str,
        output_mp3_path: str = None,
        clean_noise: bool = True,
        remove_silence: bool = True
    ) -> str:
        """Compresses audio into an ultra-lightweight mono MP3 (32 kbps, 22.05 kHz) while cleaning noise and removing silence."""
        if not output_mp3_path:
            now = datetime.now()
            output_mp3_path = os.path.join(self.raw_dir, f"{now.strftime('%Y%m%d_%H%M%S')}_dictado_min.mp3")

        audio_filters = []
        if clean_noise:
            audio_filters.append("highpass=f=100,lowpass=f=4000,afftdn=nr=10")
        if remove_silence:
            audio_filters.append(
                "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-35dB:"
                "stop_periods=-1:stop_duration=0.4:stop_threshold=-35dB"
            )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_audio_path,
            "-ac", "1",
            "-ar", "22050",
            "-b:a", "32k"
        ]
        if audio_filters:
            cmd.extend(["-af", ",".join(audio_filters)])
        cmd.extend(["-codec:a", "libmp3lame", output_mp3_path])

        logger.info(f"Compressing dictation audio with noise/silence filters to ultra-light MP3: {output_mp3_path}")
        import subprocess
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_mp3_path

    def transcribe_audio_file(self, audio_path: str, status_callback=None) -> str:
        """Transcribes an audio file (.wav, .mp3, .ogg, .flac, etc.) using Whisper AI (remote or local)."""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        mode_str = "remoto (Leria API)" if self.use_remote_whisper else "local (faster-whisper)"
        logger.info(f"Transcribing dictation audio file directly with Whisper {mode_str}: {audio_path}")

        target = getattr(config, "STUDY_TARGET", "General")
        lang = getattr(config, "STUDY_LANGUAGE", "English").lower()
        if lang.startswith("span") or target.upper() == "EIR":
            dictation_prompt = (
                f"Dictado estructurado para apuntes docentes y {target}. "
                "Comandos de puntuación y estructura: punto, coma, dos puntos, abro paréntesis, "
                "cierro paréntesis, entre paréntesis, abro comillas, cierro comillas, subpunto, guión."
            )
        else:
            dictation_prompt = (
                f"Dictado estructurado / Structured dictation for study notes and {target}. "
                "Punctuation and structure commands: period, comma, colon, open parenthesis, "
                "close parenthesis, in parentheses, open quotes, close quotes, sub-item, dash, bullet."
            )
        transcriber = AudioTranscriber(
            audio_path,
            tempfile.gettempdir(),
            include_timestamps=False,
            initial_prompt=dictation_prompt,
            use_remote=self.use_remote_whisper
        )
        temp_txt_path = transcriber.transcribe(status_callback=status_callback)

        raw_text = ""
        if os.path.exists(temp_txt_path):
            with open(temp_txt_path, "r", encoding="utf-8") as f:
                raw_text = f.read().strip()
            try:
                os.remove(temp_txt_path)
            except OSError:
                pass

        if not raw_text:
            raise ValueError("No intelligible speech detected in audio. Please speak clearly and close to the microphone.")

        logger.info(f"Whisper {mode_str} transcription completed successfully.")
        return raw_text

    def generate_notes_from_text(self, dictation_text: str, status_callback=None) -> tuple[str, str]:
        """Generates structured markdown study notes from transcribed text via LLM."""
        if not dictation_text or not dictation_text.strip():
            raise ValueError("Dictation text is empty. Cannot generate notes.")

        if status_callback:
            status_callback("Processing dictation with AI...", 0.5)

        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M")
        raw_text_filename = f"{timestamp}_dictado_bruto.txt"
        raw_text_path = os.path.join(self.raw_dir, raw_text_filename)

        with open(raw_text_path, "w", encoding="utf-8") as f:
            f.write(dictation_text)

        from pipeline.dictation_preprocessor import DictationPreprocessor
        preprocessed_text = DictationPreprocessor.process(dictation_text)

        logger.info("Sending preprocessed dictation to LLM for structured notes generation...")
        formatted_notes = self.llm_manager.process_node(
            system_prompt=DICTATION_NOTES_PROMPT,
            user_content=preprocessed_text
        )

        md_filename = f"{timestamp}_dictado.md"
        md_path = os.path.join(self.output_dir, md_filename)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(formatted_notes)

        from pipeline.docx_exporter import DocxExporter
        DocxExporter.convert_file(md_path)
        DocxExporter.convert_file(raw_text_path)

        if status_callback:
            status_callback("Dictation notes generated successfully in .md and .docx!", 1.0)

        logger.info(f"Dictation study notes saved to: {md_path} and .docx equivalent")
        return md_path, raw_text_path

    def run_from_audio(self, audio_path: str, status_callback=None) -> tuple[str, str, str]:
        """Full pipeline: transcribes uncompressed audio, generates AI study notes, and saves compressed MP3 backup."""
        if status_callback:
            mode_desc = "remote Whisper" if self.use_remote_whisper else "local Whisper"
            status_callback(f"Transcribing dictation ({mode_desc})...", 0.2)

        if status_callback:
            dictation_text = self.transcribe_audio_file(audio_path, status_callback=status_callback)
        else:
            dictation_text = self.transcribe_audio_file(audio_path)

        md_path, raw_text_path = self.generate_notes_from_text(dictation_text, status_callback=status_callback)

        if status_callback:
            status_callback("Saving compressed MP3 backup (32k mono)...", 0.85)

        backup_mp3_path = self.compress_to_ultra_light_mp3(audio_path)

        if status_callback:
            status_callback("Dictation processed and backed up successfully!", 1.0)

        return md_path, raw_text_path, backup_mp3_path

    def run_from_file(self, file_path: str, status_callback=None) -> tuple[str, str, str | None]:
        """Processes either an audio file or an existing raw text file (.txt)."""
        if file_path.lower().endswith(".txt"):
            if status_callback:
                status_callback("Reading raw dictation text...", 0.2)
            with open(file_path, "r", encoding="utf-8") as f:
                dictation_text = f.read()
            md_path, raw_text_path = self.generate_notes_from_text(dictation_text, status_callback=status_callback)
            return md_path, raw_text_path, None
        else:
            return self.run_from_audio(file_path, status_callback=status_callback)


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Transcribe voice dictation audio and generate structured study notes.")
    parser.add_argument("--audio", help="Path to input audio file (.wav, .mp3, .m4a, .flac, .ogg).")
    parser.add_argument("--file", help="Path to input audio file or raw transcription text file (.txt).")
    parser.add_argument("--output-dir", help="Output directory for generated notes.")
    parser.add_argument("--local-whisper", action="store_true", help="Force local faster-whisper instead of remote API.")

    args = parser.parse_args()
    target_file = args.audio or args.file

    if not target_file:
        print("[ERROR] Please provide an audio file via --audio <file> or --file <path>.")
        sys.exit(1)

    if not os.path.exists(target_file):
        print(f"[ERROR] Target file not found: {target_file}")
        sys.exit(1)

    use_remote = not args.local_whisper
    generator = VoiceDictationNotesGenerator(
        output_dir=args.output_dir,
        use_remote_whisper=use_remote
    )

    try:
        md_path, raw_path, backup_path = generator.run_from_file(target_file)
        print(f"\n[SUCCESS] Dictation notes generated at: {md_path}")
        print(f"[SUCCESS] Raw text backup saved at: {raw_path}")
        if backup_path:
            print(f"[SUCCESS] Ultra-light MP3 backup saved at: {backup_path}\n")
    except Exception as e:
        logger.exception("Dictation Notes generation failed:")
        sys.exit(1)
