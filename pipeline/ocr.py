import os
import logging
import re
import sys

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

# Add parent directory to path to import pipeline_config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pipeline_config

logger = logging.getLogger(__name__)

class VideoOCRExtractor:
    """Extracts text from a video file periodically using OCR (Tesseract) and cleans up UI overlays."""
    
    def __init__(self, video_path: str, temp_dir: str):
        self.video_path = video_path
        self.temp_dir = temp_dir
        self.output_temp_file = os.path.join(temp_dir, "ocr_temp.txt")
        
    def _get_word_set(self, text: str) -> set:
        """Returns a set of words from text, filtered for basic noise."""
        return {word.strip(",.()[]{}:;\"'").lower() for word in text.split() if len(word) > 2}

    def _is_similar(self, text1: str, text2: str, threshold: float = 0.8) -> bool:
        """Calculates Jaccard similarity between two texts to skip redundant slides."""
        words1 = self._get_word_set(text1)
        words2 = self._get_word_set(text2)
        if not words1 or not words2:
            return False
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        return len(intersection) / len(union) >= threshold

    def _clean_text(self, text: str) -> str:
        """Filters out lines containing Zoom/browser UI overlays, timestamps and watermarks."""
        cleaned_lines = []
        
        # UI boilerplate patterns to ignore (case-insensitive)
        ui_patterns = [
            r'zoom\s+workplace',
            r'pantalla\s+de',
            r'grabar',
            r'recording\s+mode',
            r'waiting\s+for\s+zoom',
            r'zoom\s+se\s+cerró',
            r'crear\s+un\s+informe',
            r'enviar\s+siempre',
            r'by\s+clicking',
            r'audio\s+settings',
            r'levantar\s+la\s+mano',
            r'preguntas\s+y\s+respuestas',
            r'mostrar\s+subtítulos',
            r'configuración',
            r'abandonar',
            r'el\s+anfitrión\s+volverá',
            r'recording\s+zoom\s+call',
            r'clases\s+en\s+direct',
            r'screen\s+recorder',
            r'everyone',
            r'^chat$',
            r'oposalud-opeir',
            r'elena\s+tamame',
            r'elenag@oposalud',
            r'colapso',
            r'descripción',
            r'report,\s+subject',
            r'privacy\s+policy',
            r'no\s+enviar',
            r'settings'
        ]
        
        for line in text.splitlines():
            line_strip = line.strip()
            
            # Skip empty or very short lines (often OCR noise)
            if not line_strip or len(line_strip) < 3:
                continue
                
            # Skip pure numbers/timestamp lines (e.g. "00:00:14")
            if re.match(r'^\d+:\d+(?::\d+)?$', line_strip):
                continue
                
            # Check against UI patterns
            skip = False
            for pattern in ui_patterns:
                if re.search(pattern, line_strip, re.IGNORECASE):
                    skip = True
                    break
            
            if not skip:
                cleaned_lines.append(line_strip)
                
        return "\n".join(cleaned_lines)

    def _has_changed(self, img1, img2, threshold: float = 8.0) -> bool:
        """Checks if the frame image has changed significantly using a fast thumbnail diff."""
        if img1 is None or img2 is None:
            return True
        small1 = cv2.resize(img1, (16, 16))
        small2 = cv2.resize(img2, (16, 16))
        diff = cv2.absdiff(small1, small2)
        return float(diff.mean()) > threshold

    def extract_text(self, sample_interval_sec: int = 15) -> str:
        """Samples frames from video at intervals by seeking directly, and runs OCR on changed frames."""
        if cv2 is None or pytesseract is None:
            raise ImportError(
                "OpenCV (opencv-python) and pytesseract are required for VideoOCRExtractor. "
                "Install them via: pip install 'omnilecture-studio[ocr]'"
            )
        logger.info(f"Starting OCR extraction on {self.video_path} every {sample_interval_sec}s...")
        
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {self.video_path}")
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = int(total_frames / fps) if fps > 0 else 0
        
        ocr_blocks = []
        last_text = ""
        last_frame = None
        
        # Seek and read only the frames we need, making it 100x faster
        for current_sec in range(0, duration_sec, sample_interval_sec):
            frame_no = int(current_sec * fps)
            if frame_no >= total_frames:
                break
                
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
            ret, frame = cap.read()
            if not ret:
                break
                
            # Crop the right side if configured to ignore chat
            crop_right = getattr(pipeline_config, "OCR_CROP_RIGHT", 0.0)
            if crop_right > 0.0:
                height, width = frame.shape[:2]
                crop_width = int(width * (1.0 - crop_right))
                frame = frame[:, :crop_width]
                
            # Check if frame has changed from the last processed frame
            if last_frame is not None and not self._has_changed(frame, last_frame):
                continue
                
            last_frame = frame.copy()
            
            # Preprocess frame for OCR (grayscale improves readability)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            raw_text = pytesseract.image_to_string(gray, lang="spa").strip()
            
            # Clean text to remove Zoom/webinar UI and noise
            text = self._clean_text(raw_text)
            
            minutes, seconds = divmod(current_sec, 60)
            timestamp_str = f"[{minutes:02d}:{seconds:02d}]"
            
            if text and not self._is_similar(text, last_text):
                ocr_blocks.append(f"{timestamp_str}\n{text}\n\n")
                last_text = text
                logger.info(f"Extracted new text slide at {timestamp_str}")
                
        cap.release()
        
        # Save to temp file
        os.makedirs(self.temp_workspace if hasattr(self, 'temp_workspace') else self.temp_dir, exist_ok=True)
        full_text = "".join(ocr_blocks)
        with open(self.output_temp_file, "w", encoding="utf-8") as f:
            f.write(full_text)
            
        logger.info(f"OCR extraction finished. Saved to {self.output_temp_file}")
        return self.output_temp_file
