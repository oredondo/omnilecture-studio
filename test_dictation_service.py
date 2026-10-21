import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from pipeline.dictation_service import DictationService, DictationHTTPHandler


class TestDictationService:

    @patch('pipeline.dictation_service.VoiceDictationNotesGenerator')
    def test_process_text(self, mock_gen_cls):
        mock_gen = MagicMock()
        mock_gen.generate_notes_from_text.return_value = ("/tmp/test.md", "/tmp/test.txt")
        mock_gen_cls.return_value = mock_gen

        service = DictationService()
        result = service.process_text("Texto de prueba")

        assert result["success"] is True
        assert result["markdown"] == "/tmp/test.md"
        assert result["raw_text"] == "/tmp/test.txt"
        mock_gen.generate_notes_from_text.assert_called_once_with("Texto de prueba", status_callback=None)

    @patch('pipeline.dictation_service.VoiceDictationNotesGenerator')
    def test_process_file_not_found(self, mock_gen_cls):
        service = DictationService()
        with pytest.raises(FileNotFoundError):
            service.process_file("/tmp/non_existent_file_xyz123.wav")

    @patch('pipeline.dictation_service.VoiceDictationNotesGenerator')
    def test_process_file_success(self, mock_gen_cls, tmp_path):
        dummy_audio = tmp_path / "dummy.wav"
        dummy_audio.write_text("fake audio")

        mock_gen = MagicMock()
        mock_gen.run_from_file.return_value = (str(tmp_path / "out.md"), str(tmp_path / "out.txt"), str(tmp_path / "out.mp3"))
        mock_gen_cls.return_value = mock_gen

        service = DictationService()
        result = service.process_file(str(dummy_audio))

        assert result["success"] is True
        assert result["markdown"] == str(tmp_path / "out.md")
        assert result["mp3_backup"] == str(tmp_path / "out.mp3")


class TestDictationHTTPHandler:

    def test_http_get_health(self):
        handler = DictationHTTPHandler.__new__(DictationHTTPHandler)
        handler.path = "/health"
        handler.headers = {}
        handler.service = MagicMock()
        handler.service.output_dir = "/tmp/out"

        mock_wfile = MagicMock()
        handler.wfile = mock_wfile
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()

        handler.send_response.assert_called_with(200)
        assert mock_wfile.write.called
        response_data = json.loads(mock_wfile.write.call_args[0][0].decode("utf-8"))
        assert response_data["status"] == "online"
        assert response_data["service"] == "OmniLecture Dictation Service"
