import os
from google.oauth2 import service_account

class AuthManager:
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    
    def __init__(self):
        self.creds = None
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cred_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
        self.credentials_path = os.path.join(project_root, cred_file)
    
    def get_credentials(self):
        """Get valid service account credentials"""
        if not os.path.exists(self.credentials_path):
            raise FileNotFoundError(
                f"Service account key not found at {self.credentials_path}. "
                "Please download it from Google Cloud Console."
            )
        
        self.creds = service_account.Credentials.from_service_account_file(
            self.credentials_path, scopes=self.SCOPES)
        
        return self.creds