import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent directory to path to allow importing AVA modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ava.auth_manager import AuthManager

class TestAuthManager(unittest.TestCase):
    def setUp(self):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'mock_service_account.json'
        
        self.patcher_exists = patch('os.path.exists')
        self.mock_exists = self.patcher_exists.start()
        
        self.patcher_from_file = patch('ava.auth_manager.service_account.Credentials.from_service_account_file')
        self.mock_from_file = self.patcher_from_file.start()
        
        self.mock_credentials = MagicMock()
        self.mock_from_file.return_value = self.mock_credentials
        
        self.auth_manager = AuthManager()

    def tearDown(self):
        self.patcher_exists.stop()
        self.patcher_from_file.stop()

    def test_get_credentials_success(self):
        # Simulate file exists
        self.mock_exists.return_value = True
        
        creds = self.auth_manager.get_credentials()
        self.assertIsNotNone(creds)
        self.assertEqual(creds, self.mock_credentials)
        self.mock_from_file.assert_called_once()
        
    def test_get_credentials_file_not_found(self):
        # Simulate file missing
        self.mock_exists.return_value = False
        
        with self.assertRaises(FileNotFoundError):
            self.auth_manager.get_credentials()

if __name__ == '__main__':
    unittest.main()
