import os
import sys
import argparse
import logging
import shutil
import time
import re
from datetime import datetime
from typing import Tuple, List

# Add project root directory to path to import main config and pipeline_config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config
import pipeline_config

from pipeline.ocr import VideoOCRExtractor
from pipeline.transcription import AudioTranscriber
from pipeline.graph import EIRNotesGraph
from pipeline.prompts import FINAL_REFINE_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(config.OUTPUT_DIR, "pipeline_execution.log"))
    ]
)
logger = logging.getLogger("NotesGenerator")

class NotesGenerator:
    """Orchestrates the entire video processing and EIR notes generation workflow with time-based chunking."""
    
    def __init__(self, video_path: str, audio_path: str = None, generate_anki: bool = None, use_remote_whisper: bool = None):
        self.video_path = os.path.abspath(video_path)
        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Video file not found: {self.video_path}")
            
        # Default audio path to same name with .mp3
        if audio_path:
            self.audio_path = os.path.abspath(audio_path)
        else:
            self.audio_path = os.path.splitext(self.video_path)[0] + ".mp3"
            
        if not os.path.exists(self.audio_path):
            raise FileNotFoundError(f"Audio file not found: {self.audio_path}")
            
        # Create dedicated temp workspace for this run
        self.run_id = f"run_{int(time.time())}"
        self.temp_workspace = os.path.join(config.TEMP_DIR, "pipeline_notes", self.run_id)
        os.makedirs(self.temp_workspace, exist_ok=True)
        
        # Read default from pipeline_config
        generate_anki_default = getattr(pipeline_config, "GENERATE_ANKI", True)
        self.generate_anki = generate_anki if generate_anki is not None else generate_anki_default

        if use_remote_whisper is None:
            self.use_remote_whisper = getattr(pipeline_config, "USE_REMOTE_WHISPER", True)
        else:
            self.use_remote_whisper = use_remote_whisper
        
    def _parse_filename_metadata(self) -> Tuple[str, str]:
        """Cleans the recording name to extract a clean title and subject for the EIR study notes."""
        base = os.path.splitext(os.path.basename(self.video_path))[0]
        
        # Strip prefixes like "2. " and suffixes like " (1ª)"
        clean_title = re.sub(r'^\d+\.\s*', '', base)
        clean_title = re.sub(r'\s*\([^)]*\)', '', clean_title).strip()
        
        # Infer subject
        clean_lower = clean_title.lower()
        if "investigacion" in clean_lower:
            subject = "Investigación"
        elif "respi" in clean_lower:
            subject = "Respiratorio"
        elif "salud mental" in clean_lower:
            subject = "Salud Mental"
        elif "geriatria" in clean_lower:
            subject = "Geriatría"
        elif "trabajo" in clean_lower:
            subject = "Enfermería del Trabajo"
        elif "legislacion" in clean_lower:
            subject = "Legislación"
        elif "nutri" in clean_lower:
            subject = "Nutrición"
        else:
            subject = "Enfermería Clínica"
            
        return clean_title, subject
        
    def _split_text_by_time(self, text: str, chunk_minutes: int) -> List[str]:
        """Splits timestamped text (OCR or Transcription) into chunks of specified minutes."""
        chunks = []
        current_chunk = []
        current_limit = chunk_minutes
        
        for line in text.splitlines():
            # Match formats like [MM:SS] or [HH:MM:SS]
            match = re.search(r'\[(?:(\d+):)?(\d+):(\d+)\]', line)
            if match:
                if match.group(1) is not None:
                    hours = int(match.group(1))
                    mins = int(match.group(2))
                    minutes = hours * 60 + mins
                else:
                    minutes = int(match.group(2))
                    
                if minutes >= current_limit:
                    if current_chunk:
                        chunks.append("\n".join(current_chunk))
                        current_chunk = []
                    while minutes >= current_limit:
                        current_limit += chunk_minutes
                        
            current_chunk.append(line)
            
        if current_chunk:
            chunks.append("\n".join(current_chunk))
            
        return chunks

    def run(self, sample_interval_sec: int = 15, status_callback=None) -> Tuple[str, str]:
        """Executes OCR, transcription, LangGraph processing (chunked if long), and saves the results."""
        logger.info(f"Starting notes generation. Temp workspace: {self.temp_workspace}")
        start_time = time.time()
        
        # Parse metadata
        clean_title, subject = self._parse_filename_metadata()
        logger.info(f"Parsed metadata: Title='{clean_title}', Subject='{subject}'")
        
        # Step 1: Run Video OCR
        if status_callback:
            status_callback("Extrayendo texto de diapositivas con OCR...", 0.05)
        ocr_extractor = VideoOCRExtractor(self.video_path, self.temp_workspace)
        ocr_file = ocr_extractor.extract_text(sample_interval_sec)
        
        # Step 2: Run Audio Transcription
        if status_callback:
            mode_lbl = "remoto Leria" if self.use_remote_whisper else "local"
            status_callback(f"Transcribiendo audio de la clase (Whisper {mode_lbl})...", 0.20)
        transcriber = AudioTranscriber(
            self.audio_path,
            self.temp_workspace,
            use_remote=self.use_remote_whisper
        )
        trans_file = transcriber.transcribe(status_callback=status_callback)
        
        # Read extracted texts
        with open(ocr_file, "r", encoding="utf-8") as f:
            ocr_content = f.read()
            
        with open(trans_file, "r", encoding="utf-8") as f:
            trans_content = f.read()
            
        # Step 3: Chunking text for LLM calls
        chunk_minutes = getattr(pipeline_config, "OCR_CHUNK_MINUTES", 30)
        logger.info(f"Splitting raw texts into time-based chunks of {chunk_minutes} minutes...")
        ocr_chunks = self._split_text_by_time(ocr_content, chunk_minutes)
        trans_chunks = self._split_text_by_time(trans_content, chunk_minutes)
        
        num_chunks = max(len(ocr_chunks), len(trans_chunks))
        logger.info(f"Raw inputs divided into {num_chunks} chunks.")
        
        chunk_results = []
        graph = EIRNotesGraph()
        
        for i in range(num_chunks):
            ocr_chunk = ocr_chunks[i] if i < len(ocr_chunks) else ""
            trans_chunk = trans_chunks[i] if i < len(trans_chunks) else ""
            
            chunk_title = f"{clean_title} - Parte {i+1}" if num_chunks > 1 else clean_title
            logger.info(f"Processing chunk {i+1}/{num_chunks}: '{chunk_title}'...")
            
            if status_callback:
                progress = 0.50 + (i / num_chunks) * 0.35
                status_callback(f"Consolidando y analizando bloque {i+1} de {num_chunks}...", progress)
                
            chunk_notes, chunk_anki = graph.run(
                ocr_content=ocr_chunk,
                transcription_content=trans_chunk,
                title=chunk_title,
                subject=subject,
                generate_anki=self.generate_anki
            )
            chunk_results.append((chunk_notes, chunk_anki))
            
        # Step 4: Combine Chunk Results
        if status_callback:
            status_callback("Unificando y deduplicando tarjetas...", 0.88)
            
        combined_bodies = []
        combined_questions = []
        
        # We use a set of lowercase fronts to prevent duplicate Anki flashcards
        seen_fronts = set()
        combined_anki_rows = ["Front;Back;Extra;Tags"]
        first_yaml = ""
        
        for idx, (notes_md, anki_csv_chunk) in enumerate(chunk_results):
            # Parse YAML header
            parts = notes_md.split("---")
            if len(parts) >= 3:
                if idx == 0:
                    first_yaml = "---" + parts[1] + "---\n\n"
                body_and_q = "---".join(parts[2:]).strip()
            else:
                body_and_q = notes_md.strip()
                
            # Extract questions if present
            q_split = body_and_q.split("## Cuestionario de Autoevaluación")
            body = q_split[0].strip()
            questionnaire = q_split[1].strip() if len(q_split) > 1 else ""
            
            combined_bodies.append(body)
            if questionnaire:
                combined_questions.append(questionnaire)
                
            # Process Anki rows with deduplication
            for line in anki_csv_chunk.strip().splitlines():
                if not line.strip() or line.startswith("Front;Back;Extra;Tags"):
                    continue
                parts_anki = line.split(";")
                if parts_anki:
                    front = parts_anki[0].strip().lower()
                    if front in seen_fronts:
                        continue
                    seen_fronts.add(front)
                combined_anki_rows.append(line)
                
        # Build combined files
        final_notes_md = first_yaml + "\n\n".join(combined_bodies)
        if combined_questions:
            final_notes_md += "\n\n## Cuestionario de Autoevaluación\n" + "\n\n".join(combined_questions)
            
        combined_anki_csv = "\n".join(combined_anki_rows)
        
        # Step 5: Final LLM review and optimization pass on merged notes
        logger.info("Executing final LLM refinement and review pass on merged study notes...")
        if status_callback:
            status_callback("Ejecutando revisión editorial final con IA...", 0.92)
            
        try:
            final_notes_md = graph.llm.process_node(FINAL_REFINE_PROMPT, final_notes_md)
            logger.info("Notes refinement completed successfully.")
        except Exception as e:
            logger.error(f"Failed to perform notes refinement pass (using unoptimized notes): {e}")
        
        # Step 6: Save files to output directory
        if status_callback:
            status_callback("Guardando archivos y limpiando temporales...", 0.97)
            
        base_name = os.path.splitext(os.path.basename(self.video_path))[0]
        notes_dir = os.path.join(config.OUTPUT_DIR, "apuntes")
        os.makedirs(notes_dir, exist_ok=True)
        
        # Study Notes
        notes_output_path = os.path.join(notes_dir, f"{base_name}_apuntes_EIR.md")
        with open(notes_output_path, "w", encoding="utf-8") as f:
            f.write(final_notes_md)
            
        # Anki CSV
        if self.generate_anki:
            anki_dir = os.path.join(notes_dir, "anki")
            os.makedirs(anki_dir, exist_ok=True)
            anki_output_path = os.path.join(anki_dir, f"{base_name}_anki.csv")
            with open(anki_output_path, "w", encoding="utf-8") as f:
                f.write(combined_anki_csv)
        else:
            anki_output_path = ""
            
        # Standalone Raw Files
        bruto_dir = os.path.join(notes_dir, "bruto")
        os.makedirs(bruto_dir, exist_ok=True)
        raw_ocr_path = os.path.join(bruto_dir, f"{base_name}_ocr_bruto.txt")
        raw_trans_path = os.path.join(bruto_dir, f"{base_name}_transcripcion_bruto.txt")
        shutil.copy(ocr_file, raw_ocr_path)
        shutil.copy(trans_file, raw_trans_path)

        # Export .docx versions for study notes, raw OCR, and class transcription
        from pipeline.docx_exporter import DocxExporter
        DocxExporter.convert_file(notes_output_path)
        DocxExporter.convert_file(raw_ocr_path)
        DocxExporter.convert_file(raw_trans_path)

        logger.info(f"Combined study notes saved to: {notes_output_path} and .docx equivalent")
        logger.info(f"Combined Anki CSV cards saved to: {anki_output_path}")
        logger.info(f"Raw OCR and transcription files saved to: {bruto_dir} (.txt and .docx)")
        
        # Step 7: Cleanup temporary files
        try:
            shutil.rmtree(self.temp_workspace)
            logger.info("Temporary workspace cleaned up successfully.")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary workspace: {e}")
            
        elapsed = time.time() - start_time
        logger.info(f"Pipeline executed successfully in {elapsed/60:.2f} minutes.")
        
        if status_callback:
            status_callback("¡Procesamiento completado con éxito!", 1.0)
            
        return notes_output_path, anki_output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate EIR Study Notes and Anki Cards from Class Recordings.")
    parser.add_argument("--video", required=True, help="Path to the class video (.mp4)")
    parser.add_argument("--audio", help="Path to the class audio (.mp3). Defaults to same name as video.")
    parser.add_argument("--interval", type=int, default=15, help="OCR sampling interval in seconds.")
    parser.add_argument(
        "--local-whisper",
        action="store_true",
        help="Usa Whisper local en CPU (faster-whisper) en vez del endpoint remoto"
    )
    parser.add_argument(
        "--remote-whisper",
        action="store_true",
        help="Fuerza el uso de Whisper remoto (https://leria.gal/api/v1/audio/transcriptions)"
    )
    
    args = parser.parse_args()
    
    use_remote = None
    if args.local_whisper:
        use_remote = False
    elif args.remote_whisper:
        use_remote = True

    try:
        generator = NotesGenerator(
            args.video,
            args.audio,
            generate_anki=not args.no_anki,
            use_remote_whisper=use_remote
        )
        notes_path, anki_path = generator.run(args.interval)
        print(f"\n[SUCCESS] EIR Notes generated at: {notes_path}")
        if anki_path:
            print(f"[SUCCESS] Anki CSV cards generated at: {anki_path}\n")
    except Exception as e:
        logger.exception("Notes generation failed:")
        sys.exit(1)
