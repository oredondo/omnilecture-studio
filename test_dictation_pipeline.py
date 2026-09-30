import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch

# Ensure project directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from pipeline.dictation_notes import VoiceDictationNotesGenerator


class TestVoiceDictationNotesGenerator:

    @patch('pipeline.dictation_notes.AudioTranscriber')
    def test_transcribe_audio_file_whisper_direct(self, mock_transcriber_cls):
        temp_dir = tempfile.mkdtemp()
        dummy_audio_path = os.path.join(temp_dir, "dictation.wav")
        with open(dummy_audio_path, "w") as f:
            f.write("dummy audio content")

        txt_path = os.path.join(temp_dir, "transcription_temp.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("Dictado directo procesado por Whisper IA local")

        mock_instance = MagicMock()
        mock_instance.transcribe.return_value = txt_path
        mock_transcriber_cls.return_value = mock_instance

        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        text = generator.transcribe_audio_file(dummy_audio_path)

        assert text == "Dictado directo procesado por Whisper IA local"
        assert mock_transcriber_cls.call_count == 1
        args, kwargs = mock_transcriber_cls.call_args
        assert args[0] == dummy_audio_path
        assert kwargs.get('include_timestamps') is False
        assert "Dictado estructurado" in kwargs.get('initial_prompt', '')
        mock_instance.transcribe.assert_called_once()

    @patch('pipeline.dictation_notes.LLMManager')
    def test_generate_notes_from_text_success(self, mock_llm_cls):
        mock_llm_instance = MagicMock()
        mock_llm_instance.process_node.return_value = "# Apuntes de Dictado\n\n* **Resumen**: Prueba."
        mock_llm_cls.return_value = mock_llm_instance

        temp_dir = tempfile.mkdtemp()
        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        generator.llm_manager = mock_llm_instance

        md_path, raw_path = generator.generate_notes_from_text("Dictado de prueba del usuario.")

        assert os.path.exists(md_path)
        assert os.path.exists(raw_path)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "# Apuntes de Dictado" in content

    def test_generate_notes_empty_text_error(self):
        temp_dir = tempfile.mkdtemp()
        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        with pytest.raises(ValueError, match="Dictation text is empty"):
            generator.generate_notes_from_text("")

    @patch('subprocess.run')
    def test_compress_to_ultra_light_mp3(self, mock_subproc):
        temp_dir = tempfile.mkdtemp()
        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        out_mp3 = generator.compress_to_ultra_light_mp3("input.ogg", os.path.join(temp_dir, "test_min.mp3"))

        assert out_mp3 == os.path.join(temp_dir, "test_min.mp3")
        mock_subproc.assert_called_once()
        cmd = mock_subproc.call_args[0][0]
        assert "ffmpeg" in cmd
        assert "32k" in cmd
        assert "22050" in cmd

    @patch('gi.repository.Gst.init')
    @patch('gi.repository.Gst.parse_launch')
    @patch('audio_recorder.AudioRecorder._discover_devices')
    def test_audio_recorder_pause_resume(self, mock_discover, mock_parse, mock_gst_init):
        from audio_recorder import AudioRecorder
        mock_pipeline = MagicMock()
        mock_parse.return_value = mock_pipeline
        mock_discover.return_value = ("mic_device", None)

        recorder = AudioRecorder("test.ogg")
        recorder.start()

        assert recorder._is_recording is True
        assert recorder.pause() is True
        assert recorder.is_paused() is True
        assert recorder.resume() is True
        assert recorder.is_paused() is False

    @patch('pipeline.dictation_notes.VoiceDictationNotesGenerator.compress_to_ultra_light_mp3')
    @patch('pipeline.dictation_notes.VoiceDictationNotesGenerator.transcribe_audio_file')
    @patch('pipeline.dictation_notes.LLMManager')
    def test_run_from_audio_full_workflow(self, mock_llm_cls, mock_transcribe, mock_compress):
        mock_transcribe.return_value = "Texto dictado sin compresión"
        mock_llm = MagicMock()
        mock_llm.process_node.return_value = "# Apuntes"
        mock_llm_cls.return_value = mock_llm

        temp_dir = tempfile.mkdtemp()
        mock_compress.return_value = os.path.join(temp_dir, "backup.mp3")

        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        generator.llm_manager = mock_llm

        md_path, raw_path, backup_mp3 = generator.run_from_audio("input.wav")

        assert os.path.exists(md_path)
        assert backup_mp3 == os.path.join(temp_dir, "backup.mp3")
        mock_transcribe.assert_called_once_with("input.wav")
        mock_compress.assert_called_once_with("input.wav")

    @patch('pipeline.dictation_notes.LLMManager')
    def test_dictation_generator_uses_temperature_zero(self, mock_llm_cls):
        temp_dir = tempfile.mkdtemp()
        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        mock_llm_cls.assert_called_once_with(temperature=0.0)
        assert generator.temperature == 0.0

    @patch('pipeline.dictation_notes.LLMManager')
    def test_run_from_file_txt_input(self, mock_llm_cls):
        mock_llm = MagicMock()
        mock_llm.process_node.return_value = "# Apuntes desde TXT"
        mock_llm_cls.return_value = mock_llm

        temp_dir = tempfile.mkdtemp()
        dummy_txt_path = os.path.join(temp_dir, "dictado_previo.txt")
        with open(dummy_txt_path, "w", encoding="utf-8") as f:
            f.write("Texto bruto guardado anteriormente")

        generator = VoiceDictationNotesGenerator(output_dir=temp_dir)
        generator.llm_manager = mock_llm

        md_path, raw_path, backup_mp3 = generator.run_from_file(dummy_txt_path)

        assert os.path.exists(md_path)
        assert os.path.exists(raw_path)
        assert backup_mp3 is None
        with open(md_path, "r", encoding="utf-8") as f:
            assert "# Apuntes desde TXT" in f.read()

    def test_dictation_prompt_empirical_rules(self):
        from pipeline.prompts import DICTATION_NOTES_PROMPT
        assert "ELIMINACIÓN TOTAL DE COMANDOS DE VOZ" in DICTATION_NOTES_PROMPT
        assert "CORRECCIÓN FONÉTICA" in DICTATION_NOTES_PROMPT
        assert "ESTRUCTURA Y FORMATO" in DICTATION_NOTES_PROMPT


class TestDictationPreprocessor:

    def test_spoken_punctuation_dos_puntos(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        raw = "Fases de la planificación dos puntos diagnóstico y evaluación"
        result = DictationPreprocessor.process(raw)
        assert result == "Fases de la planificación: diagnóstico y evaluación"

    def test_spoken_punctuation_parenthesis(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        raw1 = "Raynald Pineault abro paréntesis 1984 cierro paréntesis define el proceso"
        assert DictationPreprocessor.process(raw1) == "Raynald Pineault (1984) define el proceso"

        raw2 = "planificación táctica entre paréntesis cartera de servicios, contratos"
        assert "(cartera de servicios)" in DictationPreprocessor.process(raw2)

        raw3 = "Pineault de pánterismo solución óptima, continúa el plan"
        assert "(solución óptima)" in DictationPreprocessor.process(raw3)

    def test_spoken_punctuation_quotes(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        raw = "Se define como abro comillas proceso continuo cierro comillas"
        assert DictationPreprocessor.process(raw) == 'Se define como "proceso continuo"'

    def test_spoken_structure_subpuntos_and_paragraphs(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        raw = "Etapas del plan dos puntos subpunto diagnóstico subpunto priorización punto y aparte siguiente tema"
        result = DictationPreprocessor.process(raw)
        assert "- diagnóstico" in result
        assert "- priorización" in result
        assert "\n\n" in result

    def test_remove_repetition_loops(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        raw = (
            "Es un proceso de la respiración.\n"
            "Es un proceso de la respiración.\n"
            "Es un proceso de la respiración.\n"
            "Gracias.\n"
            "Gracias.\n"
            "Diagnóstico de certeza.\n"
            "Base de tratamiento.\n"
            "Para el control de síntomas.\n"
            "Base de tratamiento.\n"
            "Para el control de síntomas.\n"
        )
        cleaned = DictationPreprocessor.remove_repetition_loops(raw)
        lines = [l for l in cleaned.splitlines() if l.strip()]
        assert lines == [
            "Es un proceso de la respiración.",
            "Diagnóstico de certeza.",
            "Base de tratamiento.",
            "Para el control de síntomas."
        ]

    def test_spoken_formatting_mayusculas(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        # Prefix
        res1 = DictationPreprocessor.process("En mayúsculas contraindicada, fisioterapia respiratoria.")
        assert "CONTRAINDICADA" in res1
        assert "en mayúsculas" not in res1.lower()

        # Prefix with ponme
        res2 = DictationPreprocessor.process("Ponme en letras mayúsculas órgano de la palabra.")
        assert "ÓRGANO DE LA PALABRA" in res2

        # Suffix
        res3 = DictationPreprocessor.process("Ponme presión negativa en letras mayúsculas.")
        assert "PRESIÓN NEGATIVA" in res3

        # Suffix with comma
        res4 = DictationPreprocessor.process("expulsión de sangre por la boca, boca en letras mayúsculas, siguiente")
        assert "BOCA" in res4

    def test_spoken_formatting_asteriscos(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        # Double asterisks
        res1 = DictationPreprocessor.process("por procesos, asterisco asterisco y gestión clínica")
        assert "★★" in res1
        assert "asterisco" not in res1.lower()

        # Un par de asteriscos
        res2 = DictationPreprocessor.process("vamos a poner aquí un par de asteriscos, que es clave")
        assert "★★" in res2

        # Single asterisk
        res3 = DictationPreprocessor.process("método Hanlon, asteriscos, más utilizado")
        assert "★" in res3

        # Clinical medical term asterixis / asterisis must NOT be altered
        res4 = DictationPreprocessor.process("El paciente presenta flapping o asterisis.")
        assert "asterisis" in res4

    def test_spoken_formatting_resaltado(self):
        from pipeline.dictation_preprocessor import DictationPreprocessor
        res = DictationPreprocessor.process("resalta este dato importante, siguiente tema")
        assert "**este dato importante**" in res


