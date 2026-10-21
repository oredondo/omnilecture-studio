import os
import sys
import pytest
import numpy as np
from unittest.mock import MagicMock, patch

# Add project root directory to path
_proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)

from pipeline.handwritten_notes import HandwrittenOCRExtractor, HandwrittenNotesGenerator


class TestHandwrittenOCRExtractor:

    @patch('PIL.Image.open')
    @patch('pytesseract.image_to_string')
    def test_extract_all_success(self, mock_tesseract, mock_pil_open, tmp_path):
        from PIL import Image

        test_img = tmp_path / "dummy_page1.jpg"
        test_img.write_text("fake image content")

        # Mock PIL image
        mock_img = Image.new("RGB", (100, 100), color="white")
        mock_pil_open.return_value = mock_img

        mock_tesseract.return_value = "Apuntes manuscritos de prueba\n- Punto 1\n- Punto 2"

        extractor = HandwrittenOCRExtractor([str(test_img)])
        full_text, pages = extractor.extract_all()

        assert "Apuntes manuscritos de prueba" in full_text
        assert len(pages) == 1
        mock_tesseract.assert_called()

    @patch('pillow_heif.register_heif_opener')
    @patch('PIL.Image.open')
    @patch('pytesseract.image_to_string')
    def test_extract_heic_image_success(self, mock_tesseract, mock_pil_open, mock_heif_reg, tmp_path):
        from PIL import Image

        test_heic = tmp_path / "photo.heic"
        test_heic.write_text("fake heic content")

        mock_img = Image.new("RGB", (100, 100), color="white")
        mock_pil_open.return_value = mock_img

        mock_tesseract.return_value = "Texto desde archivo HEIC"

        extractor = HandwrittenOCRExtractor([str(test_heic)])
        full_text, pages = extractor.extract_all()

        assert "Texto desde archivo HEIC" in full_text
        assert len(pages) == 1


class TestHandwrittenNotesGenerator:

    @patch('pipeline.handwritten_notes.HandwrittenOCRExtractor.extract_all')
    @patch('pipeline.handwritten_notes.LLMManager')
    def test_generator_run_success(self, mock_llm_cls, mock_extract_all, tmp_path):
        test_img = tmp_path / "dummy1.jpg"
        test_img.write_text("fake image content")

        mock_extract_all.return_value = ("Texto OCR manuscrito", ["Texto OCR manuscrito"])

        mock_llm_instance = MagicMock()
        mock_llm_instance.process_node.return_value = "# Apuntes Manuscritos\n\n- Punto 1\n- Punto 2"
        mock_llm_cls.return_value = mock_llm_instance

        out_dir = tmp_path / "dummy_out"
        generator = HandwrittenNotesGenerator([str(test_img)], output_dir=str(out_dir))
        generator.llm_manager = mock_llm_instance

        md_path, raw_path = generator.run()

        assert os.path.exists(md_path)
        assert os.path.exists(raw_path)
        assert md_path.endswith("_manuscrito.md")
        assert raw_path.endswith("_manuscrito_bruto.txt")
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# Apuntes Manuscritos" in content
        mock_llm_instance.process_node.assert_called_once()
