import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add parent directory and ava directory to path to allow importing AVA modules
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, 'ava'))
from ava.auth_manager import AuthManager

class TestAuthManager(unittest.TestCase):
    def setUp(self):
        os.environ['GOOGLE_CLIENT_ID'] = 'mock_client_id'
        os.environ['GOOGLE_CLIENT_SECRET'] = 'mock_client_secret'
        
        # Setup TokenStore Mock
        self.mock_token_store = MagicMock()
        
        self.auth_manager = AuthManager(self.mock_token_store)

    def test_get_credentials_success(self):
        # Simulate token_store returning valid token data
        self.mock_token_store.load.return_value = {
            "token": "mock_token",
            "refresh_token": "mock_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "mock_client_id",
            "client_secret": "mock_client_secret",
            "scopes": ["mock_scope"]
        }
        
        creds = self.auth_manager.get_credentials("test_user")
        
        self.assertIsNotNone(creds)
        self.assertEqual(creds.token, "mock_token")
        self.mock_token_store.load.assert_called_once_with("test_user")
        
    def test_get_credentials_not_found(self):
        # Simulate missing credentials
        self.mock_token_store.load.return_value = None
        
        with self.assertRaises(ValueError) as context:
            self.auth_manager.get_credentials("missing_user")
            
        self.assertTrue("sign in first" in str(context.exception))
        self.mock_token_store.load.assert_called_once_with("missing_user")

if __name__ == '__main__':
    unittest.main()
