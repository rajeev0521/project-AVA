import unittest
from unittest.mock import patch, MagicMock
import datetime
import sys
import os

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, 'ava'))
from ava.nlp_processor import NLPProcessor

class TestNLPProcessor(unittest.TestCase):
    def setUp(self):
        os.environ['GEMINI_API_KEY'] = 'fake_key'
        
        # Patch models so we don't load them during tests
        self.patcher_classifier = patch('ava.nlp_processor.IntentClassifier')
        self.mock_classifier_class = self.patcher_classifier.start()
        self.mock_classifier = MagicMock()
        self.mock_classifier_class.return_value = self.mock_classifier
        
        self.patcher_extractor = patch('ava.nlp_processor.EntityExtractor')
        self.mock_extractor_class = self.patcher_extractor.start()
        self.mock_extractor = MagicMock()
        self.mock_extractor_class.return_value = self.mock_extractor
        
        self.patcher_llm = patch('ava.nlp_processor.ChatGoogleGenerativeAI')
        self.mock_llm = self.patcher_llm.start()
        
        self.processor = NLPProcessor(user_name="Tester")

    def tearDown(self):
        self.patcher_classifier.stop()
        self.patcher_extractor.stop()
        self.patcher_llm.stop()

    def test_process_command_local_success(self):
        # Simulate high confidence local classification with complete entities
        self.mock_classifier.classify.return_value = ('create_event', 0.95)
        self.mock_extractor.extract.return_value = {
            'title': 'Meeting',
            'start_time': '2030-01-01T10:00:00',
            'end_time': '2030-01-01T11:00:00'
        }
        
        intent, entities, response = self.processor.process_command("schedule a meeting")
        
        self.assertEqual(intent, 'create_event')
        self.assertEqual(entities['title'], 'Meeting')
        self.mock_classifier.classify.assert_called_once()
        self.mock_extractor.extract.assert_called_once()

    def test_process_command_gemini_fallback(self):
        # Simulate low confidence -> triggers full Gemini extraction
        self.mock_classifier.classify.return_value = ('unknown', 0.5)
        
        # We need to mock _gemini_extract since we don't want to actually run the chain
        with patch.object(self.processor, '_gemini_extract', return_value=('read_events', {}, '')) as mock_gemini:
            intent, entities, response = self.processor.process_command("what's up")
            
            self.assertEqual(intent, 'read_events')
            mock_gemini.assert_called_once()

    def test_validate_and_fix_times(self):
        # Testing timezone fix for UTC inputs (common from LLMs)
        mock_entities = {
            'start_time': '2025-12-05T15:00:00Z',
            'end_time': '2025-12-05T16:00:00+00:00'
        }
        fixed = self.processor._validate_and_fix_times(mock_entities)
        
        # Assert the 'Z' format is converted correctly to local timezone
        self.assertNotIn('Z', fixed.get('start_time', ''))
        
        # Parse output properly and assure it is localized
        out_dt = datetime.datetime.fromisoformat(fixed['start_time'])
        self.assertIsNotNone(out_dt.tzinfo)

if __name__ == '__main__':
    unittest.main()
