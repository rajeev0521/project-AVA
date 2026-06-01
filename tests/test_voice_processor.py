import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import numpy as np

# Add parent directory to path to allow importing AVA modules
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, 'ava'))
from ava.voice_processor import VoiceProcessor

class TestVoiceProcessor(unittest.TestCase):
    def setUp(self):
        os.environ['WAKE_WORD_MODEL'] = 'hey jarvis'
        os.environ['WAKE_WORD_THRESHOLD'] = '0.5'
        
        self.patcher_pyaudio = patch('pyaudio.PyAudio')
        self.mock_pyaudio_cls = self.patcher_pyaudio.start()
        
        self.patcher_model = patch('ava.voice_processor.Model')
        self.mock_model_cls = self.patcher_model.start()
        
        self.patcher_download = patch('ava.voice_processor.openwakeword.utils.download_models')
        self.mock_download = self.patcher_download.start()
        
        # Setup PyAudio Mock
        self.mock_pa_instance = MagicMock()
        self.mock_pyaudio_cls.return_value = self.mock_pa_instance
        self.mock_stream = MagicMock()
        self.mock_pa_instance.open.return_value = self.mock_stream
        
        # Setup Model Mock
        self.mock_model_instance = MagicMock()
        self.mock_model_cls.return_value = self.mock_model_instance
        
        self.processor = VoiceProcessor()

    def tearDown(self):
        self.patcher_pyaudio.stop()
        self.patcher_model.stop()
        self.patcher_download.stop()

    def test_initialization(self):
        self.assertEqual(self.processor.threshold, 0.5)
        self.assertEqual(self.processor.chunk_size, 1280)
        
    def test_detect_wake_word_success(self):
        # Simulate PyAudio returning silence
        silence = bytes([0] * (1280 * 2))  # 1280 int16 samples
        self.mock_stream.read.return_value = silence
        
        # Simulate openwakeword returning a high score prediction once
        # Using side_effect to return > threshold on second loop frame to test progression
        self.mock_model_instance.predict.side_effect = [
            {'hey jarvis': 0.1},
            {'hey jarvis': 0.9}
        ]
        
        result = self.processor.detect_wake_word()
        self.assertTrue(result)
        self.assertEqual(self.mock_stream.read.call_count, 2)
        
    @patch('ava.voice_processor.sr.Microphone')
    @patch('ava.voice_processor.sr.Recognizer')
    def test_listen_command(self, mock_rec_cls, mock_mic_cls):
        mock_rec_instance = MagicMock()
        mock_rec_cls.return_value = mock_rec_instance
        
        # Configure mock recognizer to return a simulated transcription result
        mock_rec_instance.listen.return_value = b'audio_data'
        mock_rec_instance.recognize_whisper.return_value = "hello ava"
        
        # Inject our mock recognizer into the processor
        self.processor.recognizer = mock_rec_instance
        
        text = self.processor.listen_command()
        self.assertEqual(text, "hello ava")
        mock_rec_instance.adjust_for_ambient_noise.assert_called_once()
        mock_rec_instance.listen.assert_called_once()
        mock_rec_instance.recognize_whisper.assert_called_once()

if __name__ == '__main__':
    unittest.main()
