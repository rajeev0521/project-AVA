import os
from google.oauth2 import service_account
from logger import get_logger

logger = get_logger(__name__)


class AuthManager:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self):
        self._creds = None
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
        self.credentials_path = os.path.join(project_root, cred_file)
    
    def get_credentials(self):
        """Get valid service account credentials. Cached after first load."""
        # Return cached credentials if valid
        if self._creds is not None and self._creds.valid:
            return self._creds
        
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"Service account key not found at {self.credentials_path}. "
                "Please download it from Google Cloud Console."
            )
        
        self._creds = service_account.Credentials.from_service_account_file(
            self.credentials_path, scopes=self.SCOPES)
        
        logger.info("Service account credentials loaded and cached")
        return self._creds