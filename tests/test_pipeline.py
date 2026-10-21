import os
import sys
import tempfile
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

# Ensure the project directory is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from pipeline.ocr import VideoOCRExtractor
from pipeline.transcription import AudioTranscriber
from pipeline.llm_manager import LLMManager
from pipeline.graph import EIRNotesGraph
from pipeline.generate_notes import NotesGenerator

DUMMY_TEMP_DIR = os.path.join(tempfile.gettempdir(), "dummy_temp")


class TestVideoOCRExtractor:
    
    @patch('cv2.VideoCapture')
    @patch('pytesseract.image_to_string')
    @patch('os.makedirs')
    @patch('builtins.open')
    def test_extract_text_success(self, mock_open, mock_makedirs, mock_tesseract, mock_video_capture):
        # Mock VideoCapture behaviour
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 1.0 # 1 FPS
        
        # Mock frame as numpy array
        fake_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        
        # 2 frames read successfully, then end of stream
        mock_cap.read.side_effect = [(True, fake_frame), (True, fake_frame), (False, None)]
        mock_video_capture.return_value = mock_cap
        
        # Mock Tesseract output
        mock_tesseract.side_effect = ["Texto diapositiva 1", "Texto diapositiva 2"]
        
        extractor = VideoOCRExtractor("dummy.mp4", DUMMY_TEMP_DIR)
        output_file = extractor.extract_text(sample_interval_sec=1)
        
        assert output_file == os.path.join(DUMMY_TEMP_DIR, "ocr_temp.txt")
        mock_tesseract.assert_called()
        mock_cap.release.assert_called_once()


class TestAudioTranscriber:

    @patch('os.path.getsize', return_value=1000)
    @patch('os.path.exists', return_value=True)
    @patch('pipeline.transcription.WhisperModel')
    @patch('pipeline.transcription.subprocess.run')
    @patch('pipeline.transcription.glob.glob')
    @patch('pipeline.transcription.os.remove')
    @patch('os.makedirs')
    @patch('builtins.open')
    def test_transcribe_local_success(
        self, mock_open, mock_makedirs, mock_remove, mock_glob, mock_run, mock_whisper, mock_exists, mock_getsize
    ):
        # Mock WhisperModel behavior
        mock_model_instance = MagicMock()
        mock_whisper.return_value = mock_model_instance
        
        # Mock glob to return a dummy chunk file
        mock_glob.return_value = [os.path.join(DUMMY_TEMP_DIR, "audio_chunk_000.mp3")]
        
        # Mock segments generator
        mock_segment1 = MagicMock()
        mock_segment1.start = 10
        mock_segment1.text = "Hello world"
        
        mock_model_instance.transcribe.return_value = ([mock_segment1], MagicMock(language="es", language_probability=0.99))
        
        transcriber = AudioTranscriber("dummy.mp3", DUMMY_TEMP_DIR, use_remote=False)
        output_file = transcriber.transcribe()
        
        assert output_file == os.path.join(DUMMY_TEMP_DIR, "transcription_temp.txt")
        mock_model_instance.transcribe.assert_called_once()
        mock_run.assert_called()
        mock_glob.assert_called_once()
        mock_remove.assert_called()

    @patch('os.path.getsize', return_value=1000)
    @patch('os.path.exists', return_value=True)
    @patch('pipeline.transcription.requests.post')
    @patch('pipeline.transcription.subprocess.run')
    @patch('pipeline.transcription.glob.glob')
    @patch('pipeline.transcription.os.remove')
    @patch('os.makedirs')
    @patch('builtins.open')
    def test_transcribe_remote_success(
        self, mock_open, mock_makedirs, mock_remove, mock_glob, mock_run, mock_requests_post, mock_exists, mock_getsize
    ):
        # Mock remote request response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "Transcripcion de prueba remota"}
        mock_requests_post.return_value = mock_resp

        # Mock glob to return a dummy chunk file
        mock_glob.return_value = [os.path.join(DUMMY_TEMP_DIR, "audio_chunk_000.mp3")]

        transcriber = AudioTranscriber("dummy.mp3", DUMMY_TEMP_DIR, use_remote=True, api_key="test_key")
        output_file = transcriber.transcribe()

        assert output_file == os.path.join(DUMMY_TEMP_DIR, "transcription_temp.txt")
        mock_requests_post.assert_called_once()
        mock_run.assert_called()
        mock_glob.assert_called_once()
        mock_remove.assert_called()


class TestLLMManager:

    @patch('pipeline.llm_manager.ChatOpenAI.invoke')
    def test_process_node_success(self, mock_invoke):
        mock_invoke.return_value = AIMessage(content="Resultado del LLM")
        
        manager = LLMManager()
        response = manager.process_node("System prompt", "User content")
        
        assert response == "Resultado del LLM"
        mock_invoke.assert_called_once()


class TestEIRNotesGraph:

    @patch('pipeline.graph.LLMManager')
    def test_graph_runs_successfully(self, mock_llm_manager_class):
        mock_llm_instance = MagicMock()
        mock_llm_manager_class.return_value = mock_llm_instance
        
        # Smart mock based on prompt contents to prevent execution order issues
        def mock_process_node(system_prompt, user_content=""):
            if "consolidate" in system_prompt:
                return "Texto consolidado"
            elif "segment" in system_prompt:
                return "Texto segmentado"
            elif "generate_notes" in system_prompt:
                return "Apuntes EIR finales"
            elif "generate_anki" in system_prompt:
                return "Front;Back;Extra;Tags"
            return "Default"
            
        mock_llm_instance.process_node.side_effect = mock_process_node
        
        # Patch prompt variables in graph.py to identify prompt types during test execution
        with patch('pipeline.graph.CONSOLIDATE_PROMPT', 'consolidate'), \
             patch('pipeline.graph.SEGMENT_PROMPT', 'segment'), \
             patch('pipeline.graph.GENERATE_NOTES_PROMPT', 'generate_notes {title} {date} {subject}'), \
             patch('pipeline.graph.GENERATE_ANKI_PROMPT', 'generate_anki'):
             
            graph = EIRNotesGraph()
            final_notes, anki_csv = graph.run("ocr content", "transcription content")
            
            assert final_notes == "Apuntes EIR finales"
            assert anki_csv == "Front;Back;Extra;Tags"
            assert mock_llm_instance.process_node.call_count == 4
