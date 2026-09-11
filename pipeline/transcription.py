import os
import time
import logging
import subprocess
import glob
import requests
from faster_whisper import WhisperModel
import pipeline_config

logger = logging.getLogger(__name__)


class AudioTranscriber:
    """Transcribes audio file to text in memory-efficient chunks using remote Leria Whisper API or local faster-whisper."""

    def __init__(
        self,
        audio_path: str,
        temp_dir: str,
        include_timestamps: bool = True,
        initial_prompt: str = None,
        use_remote: bool = None,
        remote_endpoint: str = None,
        api_key: str = None
    ):
        self.audio_path = audio_path
        self.temp_dir = temp_dir
        self.include_timestamps = include_timestamps
        self.initial_prompt = initial_prompt
        self.output_temp_file = os.path.join(temp_dir, "transcription_temp.txt")

        # Remote vs local configuration (defaults to True as per user specification)
        if use_remote is None:
            self.use_remote = getattr(pipeline_config, "USE_REMOTE_WHISPER", True)
        else:
            self.use_remote = use_remote

        self.remote_endpoint = remote_endpoint or getattr(
            pipeline_config, "WHISPER_ENDPOINT", "https://leria.gal/api/v1/audio/transcriptions"
        )
        self.api_key = api_key or getattr(pipeline_config, "API_KEY", "")

    def transcribe(self, status_callback=None) -> str:
        """Transcribes audio using remote Whisper API endpoint (default) or local faster-whisper."""
        os.makedirs(self.temp_dir, exist_ok=True)

        if not os.path.exists(self.audio_path) or os.path.getsize(self.audio_path) == 0:
            raise ValueError("El archivo de audio no existe o está vacío.")

        normalized_wav = os.path.join(self.temp_dir, f"norm_{int(time.time() * 1000)}.wav")
        logger.info(f"Normalizing audio {self.audio_path} to 16kHz mono PCM WAV...")

        cmd_norm = [
            "ffmpeg", "-y", "-i", self.audio_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ac", "1", "-ar", "16000", "-codec:a", "pcm_s16le",
            normalized_wav
        ]
        try:
            subprocess.run(cmd_norm, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            audio_source_path = normalized_wav
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode('utf-8', errors='ignore')
            logger.error(f"FFmpeg audio normalization failed: {err_msg}")
            raise ValueError("El archivo de audio no contiene datos válidos o está dañado.")

        try:
            if self.use_remote:
                return self._transcribe_remote(audio_source_path, status_callback=status_callback)
            else:
                return self._transcribe_local(audio_source_path, status_callback=status_callback)
        finally:
            if os.path.exists(normalized_wav):
                try:
                    os.remove(normalized_wav)
                except OSError:
                    pass

    def _send_remote_chunk(self, chunk_path: str, max_retries: int = 3) -> str:
        """Sends an audio file chunk to the remote Whisper endpoint with retries."""
        if not self.api_key:
            raise ValueError("API_KEY no encontrada en pipeline_config.py para usar Whisper Remoto.")

        headers = {"Authorization": f"Bearer {self.api_key}"}
        file_ext = os.path.splitext(chunk_path)[1].lower()
        content_type = "audio/mpeg" if file_ext == ".mp3" else "audio/wav"
        data = {"language": "es"}
        if self.initial_prompt:
            data["prompt"] = self.initial_prompt

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                with open(chunk_path, "rb") as f:
                    files = {"file": (os.path.basename(chunk_path), f, content_type)}
                    response = requests.post(
                        self.remote_endpoint,
                        headers=headers,
                        files=files,
                        data=data,
                        timeout=180
                    )
                if response.status_code == 200:
                    result = response.json()
                    return result.get("text", "").strip()
                else:
                    last_error = f"HTTP {response.status_code}: {response.text}"
                    logger.warning(f"Intento {attempt}/{max_retries} a Whisper remoto falló: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Intento {attempt}/{max_retries} a Whisper remoto lanzó excepción: {e}")

            if attempt < max_retries:
                time.sleep(attempt * 2)

        raise RuntimeError(f"Error en servidor Whisper remoto ({self.remote_endpoint}): {last_error}")

    def _transcribe_remote(self, audio_source_path: str, status_callback=None) -> str:
        """Transcribes audio in 10-minute MP3 chunks using the remote Whisper API endpoint."""
        logger.info(f"Transcribing audio using remote Whisper API ({self.remote_endpoint})...")
        chunk_pattern = os.path.join(self.temp_dir, "audio_chunk_%03d.mp3")

        try:
            cmd = [
                "ffmpeg", "-y", "-i", audio_source_path,
                "-f", "segment", "-segment_time", "600",
                "-c:a", "libmp3lame", "-b:a", "64k", "-ac", "1",
                chunk_pattern
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            chunk_files = sorted(glob.glob(os.path.join(self.temp_dir, "audio_chunk_*")))
            if not chunk_files:
                chunk_files = [audio_source_path]
        except Exception as e:
            logger.warning(f"Segment splitting fallback to single file: {e}")
            chunk_files = [audio_source_path]

        logger.info(f"Audio split into {len(chunk_files)} chunks for remote Whisper processing.")

        transcribed_segments = []
        for idx, chunk_file in enumerate(chunk_files):
            offset_sec = idx * 600
            msg = f"Transcribiendo chunk {idx+1}/{len(chunk_files)} con Whisper remoto..."
            logger.info(f"{msg} ({os.path.basename(chunk_file)}, Offset: {offset_sec}s)...")
            if status_callback:
                status_callback(msg, 0.20 + (idx / len(chunk_files)) * 0.20)

            chunk_text = self._send_remote_chunk(chunk_file)
            if chunk_text:
                lines = [line_item.strip() for line_item in chunk_text.splitlines() if line_item.strip()]
                if not lines and chunk_text.strip():
                    lines = [chunk_text.strip()]

                if self.include_timestamps:
                    minutes, seconds = divmod(offset_sec, 60)
                    timestamp_str = f"[{minutes:02d}:{seconds:02d}]"
                    for line in lines:
                        transcribed_segments.append(f"{timestamp_str} {line}\n")
                else:
                    for line in lines:
                        transcribed_segments.append(f"{line}\n")

            try:
                os.remove(chunk_file)
            except Exception as e:
                logger.warning(f"Failed to remove temporary chunk file {chunk_file}: {e}")

        full_text = "".join(transcribed_segments)
        with open(self.output_temp_file, "w", encoding="utf-8") as f:
            f.write(full_text)

        logger.info(f"Remote Whisper transcription finished. Saved to {self.output_temp_file}")
        return self.output_temp_file

    def _transcribe_local(self, audio_source_path: str, status_callback=None) -> str:
        """Transcribes audio using local faster-whisper CPU model."""
        whisper_model = getattr(pipeline_config, "WHISPER_MODEL", "base")
        logger.info(f"Loading local Whisper model '{whisper_model}' on CPU (int8 quantization)...")
        model = WhisperModel(whisper_model, device="cpu", compute_type="int8")

        try:
            logger.info("Splitting normalized audio into 30-minute chunks for local Whisper...")
            chunk_pattern = os.path.join(self.temp_dir, "audio_chunk_%03d.wav")

            cmd = [
                "ffmpeg", "-y", "-i", audio_source_path,
                "-f", "segment", "-segment_time", "1800",
                "-c", "copy", chunk_pattern
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            chunk_files = sorted(glob.glob(os.path.join(self.temp_dir, "audio_chunk_*")))
            if not chunk_files:
                chunk_files = [audio_source_path]
        except Exception as e:
            logger.warning(f"Segment splitting fallback to single file: {e}")
            chunk_files = [audio_source_path]

        logger.info(f"Audio split successfully into {len(chunk_files)} chunks for local Whisper.")

        transcribed_segments = []

        for idx, chunk_file in enumerate(chunk_files):
            offset_sec = idx * 1800
            msg = f"Transcribiendo chunk {idx+1}/{len(chunk_files)} con Whisper local..."
            logger.info(f"{msg} ({os.path.basename(chunk_file)} Offset: {offset_sec}s)...")
            if status_callback:
                status_callback(msg, 0.20 + (idx / len(chunk_files)) * 0.20)

            segments, info = model.transcribe(
                chunk_file,
                beam_size=5,
                language="es",
                initial_prompt=self.initial_prompt,
                vad_filter=True
            )

            if idx == 0:
                logger.info(f"Detected language: {info.language} with probability {info.language_probability:.2f}")

            for segment in segments:
                text_clean = segment.text.strip()
                if not text_clean:
                    continue
                if self.include_timestamps:
                    current_sec = int(segment.start) + offset_sec
                    minutes, seconds = divmod(current_sec, 60)
                    timestamp_str = f"[{minutes:02d}:{seconds:02d}]"
                    line = f"{timestamp_str} {text_clean}\n"
                else:
                    line = f"{text_clean}\n"
                transcribed_segments.append(line)

            try:
                os.remove(chunk_file)
            except Exception as e:
                logger.warning(f"Failed to remove temporary chunk file {chunk_file}: {e}")

        full_text = "".join(transcribed_segments)
        with open(self.output_temp_file, "w", encoding="utf-8") as f:
            f.write(full_text)

        logger.info(f"Local Whisper transcription finished. Saved to {self.output_temp_file}")
        return self.output_temp_file
