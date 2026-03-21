import unittest
from unittest.mock import patch, MagicMock
import datetime
import sys
import os

# Add parent directory to path to allow importing AVA modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ava.calendar_manager import CalendarManager
from ava.auth_manager import AuthManager

class TestCalendarManager(unittest.TestCase):
    def setUp(self):
        self.patcher_build = patch('ava.calendar_manager.build')
        self.mock_build = self.patcher_build.start()
        
        self.patcher_creds = patch('ava.auth_manager.service_account.Credentials')
        self.mock_credentials = self.patcher_creds.start()

        # Setup AuthManager Mock
        self.mock_auth = AuthManager()
        self.mock_auth.get_credentials = MagicMock(return_value=self.mock_credentials)
        
        # Setup Google API build mock
        self.mock_service = MagicMock()
        self.mock_build.return_value = self.mock_service
        self.mock_events = self.mock_service.events()
        
        # Initialize
        self.manager = CalendarManager(self.mock_auth)

    def tearDown(self):
        self.patcher_build.stop()
        self.patcher_creds.stop()

    def test_get_calendar_service(self):
        # Verify credentials were conceptually requested
        self.assertIsNotNone(self.manager.service)
        self.mock_auth.get_credentials.assert_called_once()

    def test_execute_create_event_success(self):
        # Mocking the external execute callback
        self.mock_events.insert.return_value.execute.return_value = {'htmlLink': 'http://mock.calendar.link'}
        
        # Test input payload (using FUTURE year to bypass past-event check)
        entities = {
            'title': 'Test Integration Event',
            'start_time': '2030-01-01T10:00:00Z',
            'end_time': '2030-01-01T11:00:00Z'
        }
        
        result = self.manager.execute_command('create_event', entities)
        
        # Assertions
        self.assertIn('successfully created', result.lower())
        self.mock_events.insert.assert_called_once()
        
        # Verify the structure passed to google API
        args, kwargs = self.mock_events.insert.call_args
        body = kwargs.get('body')
        self.assertEqual(body['summary'], 'Test Integration Event')
        self.assertTrue(body['start']['dateTime'].startswith('2030-01-01T'))

    def test_execute_read_events_empty(self):
        # Setup mock behavior simulating no upcoming events
        self.mock_events.list().execute.return_value = {'items': []}
        
        result = self.manager.execute_command('read_events', {})
        self.assertIn("no events found", result.lower())
        
    def test_execute_read_events_found(self):
        # Setup mock behavior simulating 1 event
        self.mock_events.list().execute.return_value = {'items': [
            {'summary': 'Rigorous Planning', 'start': {'dateTime': '2030-02-01T15:00:00-05:00'}, 'end': {'dateTime': '2030-02-01T16:00:00-05:00'}}
        ]}
        
        result = self.manager.execute_command('read_events', {})
        self.assertIn("Rigorous Planning", result)

    def test_execute_update_event_missing_id(self):
        # Tests internal validation error when event ID is not provided
        result = self.manager.execute_command('update_event', {'title': 'New Event Title'})
        self.assertIn("error", result.lower())
        self.assertIn("could not identify", result.lower())
        self.mock_events.update.assert_not_called()

if __name__ == '__main__':
    unittest.main()
