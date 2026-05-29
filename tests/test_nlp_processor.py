import unittest
from unittest.mock import patch, MagicMock
import datetime
from tzlocal import get_localzone
import sys
import os

# Add parent directory to path to allow importing AVA modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ava.nlp_processor import NLPProcessor

class TestNLPProcessor(unittest.TestCase):
    def setUp(self):
        os.environ['GEMINI_API_KEY'] = 'fake_key'
        self.patcher_llm = patch('ava.nlp_processor.ChatGoogleGenerativeAI')
        self.mock_llm = self.patcher_llm.start()
        self.processor = NLPProcessor(user_name="Tester")
        self.local_tz = get_localzone()

    def tearDown(self):
        self.patcher_llm.stop()

    def test_fallback_parsing_create_event_today(self):
        # Rigorous test of intent fallback and regex logic
        intent, entities = self.processor._fallback_parsing("schedule a meeting for 2 pm")
        self.assertEqual(intent, 'create_event')
        self.assertEqual(entities['title'], 'Meeting')
        
        # Check if the parsed hour is 14 (2 PM)
        self.assertTrue('T14:00' in entities['start_time'])

    def test_fallback_parsing_complex_time(self):
        # Testing exact time formatting "2:30 pm"
        intent, entities = self.processor._fallback_parsing("schedule an appointment for 2:30 pm")
        self.assertEqual(intent, 'create_event')
        self.assertEqual(entities['title'], 'Appointment')
        
        self.assertTrue('T14:00' in entities['start_time'])

    def test_validate_and_fix_times(self):
        # Testing timezone fix for UTC inputs (common from LLMs)
        mock_entities = {
            'start_time': '2025-12-05T15:00:00Z',
            'end_time': '2025-12-05T16:00:00+00:00'
        }
        fixed = self.processor._validate_and_fix_times(mock_entities)
        
        # Assert the 'Z' format is converted correctly to local timezone
        self.assertNotIn('Z', fixed['start_time'])
        
        # Parse output properly and assure it is localized
        out_dt = datetime.datetime.fromisoformat(fixed['start_time'])
        self.assertIsNotNone(out_dt.tzinfo)

    def test_fallback_parsing_delete(self):
        # Tests intent prioritizing logic
        intent, entities = self.processor._fallback_parsing("please cancel my meeting")
        self.assertEqual(intent, 'delete_event')
        self.assertEqual(entities, {})

if __name__ == '__main__':
    unittest.main()
