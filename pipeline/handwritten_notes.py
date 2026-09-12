import os
import sys
import time
import cv2
import pytesseract
import logging
import argparse
import shutil
from typing import List, Tuple, Callable, Optional
from datetime import datetime

# Add project root directory to sys.path to import config and pipeline_config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config
import pipeline_config
from pipeline.llm_manager import LLMManager
from pipeline.prompts import HANDWRITTEN_TRANSCRIPTION_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(config.OUTPUT_DIR, "handwritten_notes.log"))
    ]
)
logger = logging.getLogger("HandwrittenNotesGenerator")

class HandwrittenOCRExtractor:
    """Extracts text from handwritten note images using OpenCV image preprocessing and Tesseract OCR."""
    
    def __init__(self, image_paths: List[str]):
        self.image_paths = [os.path.abspath(p) for p in image_paths if os.path.exists(p)]
        if not self.image_paths:
            raise FileNotFoundError("No valid image files provided for handwritten OCR extraction.")
            
    def _preprocess_image(self, img_path: str):
        """Applies image thumbnail resizing (max 1200px), grayscale conversion, and CLAHE contrast enhancement for handwritten text."""
        import numpy as np
        from PIL import Image
        ext = os.path.splitext(img_path)[1].lower()
        pil_img = None
        
        # Load image via PIL / pillow_heif for HEIC or general formats
        if ext in (".heic", ".heif"):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
                pil_img = Image.open(img_path).convert("RGB")
            except Exception as e:
                logger.warning(f"Could not load HEIC via pillow_heif ({img_path}): {e}")
        
        if pil_img is None:
            try:
                pil_img = Image.open(img_path).convert("RGB")
            except Exception:
                cv_img = cv2.imread(img_path)
                if cv_img is not None:
                    pil_img = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))

        if pil_img is None:
            logger.warning(f"Could not load image: {img_path}")
            return None

        if not hasattr(pil_img, "thumbnail"):
            pil_img = Image.fromarray(np.uint8(pil_img))

        # Downsample image thumbnail to max 1200px for fast Tesseract OCR and clean stroke resolution
        pil_img.thumbnail((1200, 1200), Image.Resampling.BILINEAR)
            
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Adaptive histogram equalization for contrast enhancement (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        return enhanced

    def extract_all(self, status_callback: Optional[Callable[[str, float], None]] = None) -> Tuple[str, List[str]]:
        """Processes all provided images and returns concatenated raw OCR text and per-page text list."""
        page_texts = []
        total = len(self.image_paths)
        
        for idx, img_path in enumerate(self.image_paths, start=1):
            file_name = os.path.basename(img_path)
            if status_callback:
                progress = 0.1 + (idx / total) * 0.4 # 10% to 50%
                status_callback(f"Procesando imagen {idx}/{total}: {file_name}...", progress)
                
            logger.info(f"Extracting OCR text from image {idx}/{total}: {file_name}")
            
            enhanced = self._preprocess_image(img_path)
            if enhanced is None:
                continue
                
            # Perform fast Tesseract OCR
            raw_text = pytesseract.image_to_string(enhanced, lang="spa").strip()
                
            page_header = f"=== PÁGINA {idx} ({file_name}) ===\n"
            page_content = f"{page_header}{raw_text if raw_text else '[Sin texto detectado]'}\n\n"
            page_texts.append(page_content)
            
        full_ocr_text = "".join(page_texts)
        return full_ocr_text, page_texts


class HandwrittenNotesGenerator:
    """Orchestrates the conversion of handwritten note photographs into structured Markdown files."""
    
    def __init__(self, image_paths: List[str], output_dir: Optional[str] = None):
        self.image_paths = sorted([os.path.abspath(p) for p in image_paths if os.path.exists(p)])
        if not self.image_paths:
            raise FileNotFoundError("No valid image files provided.")
            
        self.output_dir = output_dir if output_dir else os.path.join(config.OUTPUT_DIR, "apuntes_manuscritos")
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.run_id = f"handwritten_{int(time.time())}"
        self.temp_workspace = os.path.join(config.TEMP_DIR, "handwritten_notes", self.run_id)
        os.makedirs(self.temp_workspace, exist_ok=True)
        
        self.llm_manager = LLMManager()

    def run(self, status_callback: Optional[Callable[[str, float], None]] = None) -> Tuple[str, str]:
        """Runs OCR extraction, queries LLM with zero-invention prompt, and saves Markdown file.
        
        Returns:
            Tuple[str, str]: (path_to_markdown_file, path_to_raw_ocr_file)
        """
        start_time = time.time()
        logger.info(f"Starting Handwritten Notes Pipeline for {len(self.image_paths)} images...")
        
        if status_callback:
            status_callback("Starting analysis of handwritten photos...", 0.05)
            
        # Step 1: Perform OCR extraction
        extractor = HandwrittenOCRExtractor(self.image_paths)
        raw_ocr_text, page_texts = extractor.extract_all(status_callback=status_callback)
        
        if not raw_ocr_text.strip():
            raise ValueError("Could not extract any text from the provided images.")
            
        # Save raw OCR file in temp workspace
        raw_ocr_path = os.path.join(self.temp_workspace, "ocr_manuscrito_bruto.txt")
        with open(raw_ocr_path, "w", encoding="utf-8") as f:
            f.write(raw_ocr_text)
            
        # Step 2: Query LLM to transcribe & format faithfully
        if status_callback:
            status_callback("Generating faithful Markdown with AI (Zero Invention)...", 0.60)
            
        logger.info("Sending raw OCR content to LLM for faithful Markdown conversion...")
        markdown_content = self.llm_manager.process_node(
            system_prompt=HANDWRITTEN_TRANSCRIPTION_PROMPT,
            user_content=raw_ocr_text
        )
        
        if status_callback:
            status_callback("Saving files and finalizing...", 0.90)
            
        # Step 3: Write outputs
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M")
        
        # Output directory organization
        notes_dir = self.output_dir
        os.makedirs(notes_dir, exist_ok=True)
        
        output_md_path = os.path.join(notes_dir, f"{timestamp_str}_manuscrito.md")
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
            
        # Raw file backup
        bruto_dir = os.path.join(notes_dir, "bruto")
        os.makedirs(bruto_dir, exist_ok=True)
        output_raw_path = os.path.join(bruto_dir, f"{timestamp_str}_manuscrito_bruto.txt")
        shutil.copy(raw_ocr_path, output_raw_path)

        # Export .docx documents for handwritten notes
        from pipeline.docx_exporter import DocxExporter
        DocxExporter.convert_file(output_md_path)
        DocxExporter.convert_file(output_raw_path)

        # Cleanup workspace
        try:
            shutil.rmtree(self.temp_workspace)
        except Exception as e:
            logger.warning(f"Could not clean up temp workspace: {e}")
            
        elapsed = time.time() - start_time
        logger.info(f"Handwritten Notes Pipeline completed in {elapsed:.2f}s. Output: {output_md_path}")
        
        if status_callback:
            status_callback("Handwritten notes generated successfully!", 1.0)
            
        return output_md_path, output_raw_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Markdown file from Handwritten Note Photographs.")
    parser.add_argument("--images", nargs="+", help="Paths to handwritten note image files (.jpg, .png, etc.)")
    parser.add_argument("--dir", help="Directory containing handwritten note image files.")
    parser.add_argument("--output-dir", help="Output directory for generated .md file.")
    
    args = parser.parse_args()
    
    input_images = []
    if args.images:
        input_images.extend(args.images)
    if args.dir and os.path.isdir(args.dir):
        valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".heic", ".heif")
        for root, _, files in os.walk(args.dir):
            for f in files:
                if f.lower().endswith(valid_exts):
                    input_images.append(os.path.join(root, f))
                    
    if not input_images:
        print("[ERROR] Please provide --images or --dir with valid image files.")
        sys.exit(1)
        
    try:
        generator = HandwrittenNotesGenerator(input_images, output_dir=args.output_dir)
        md_path, raw_path = generator.run()
        print(f"\n[SUCCESS] Handwritten Notes Markdown generated at: {md_path}")
        print(f"[SUCCESS] Raw OCR backup saved at: {raw_path}\n")
    except Exception as e:
        logger.exception("Handwritten Notes generation failed:")
        sys.exit(1)
