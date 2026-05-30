"""
Auth Manager for AVA — Google OAuth 2.0 per-user authentication.
Handles the full OAuth flow: authorization URL generation, code exchange,
credential refresh, and per-user Calendar API service construction.
"""

import os
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from logger import get_logger

logger = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def creds_to_dict(creds: Credentials) -> dict:
    """Serialize a Credentials object to a dict suitable for storage."""
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else list(SCOPES),
    }


class AuthManager:
    """
    OAuth 2.0 authentication manager for per-user Google Calendar access.

    Each user signs in with their own Google account. Credentials are stored
    in a token_store (SupabaseTokenStore) and refreshed automatically.
    """

    def __init__(self, token_store):
        """
        Initialize AuthManager.

        Args:
            token_store: A SupabaseTokenStore (or any object with save/load methods)
                         for persisting per-user OAuth credentials.
        """
        self.token_store = token_store
        self.client_id = os.environ["GOOGLE_CLIENT_ID"]
        self.client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
        self.redirect_uri = os.environ.get(
            "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback"
        )

    def _client_config(self) -> dict:
        """Build the client config dict for OAuth flow."""
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.redirect_uri],
            }
        }

    def get_authorization_url(self, state: str) -> str:
        """
        Generate the Google OAuth consent screen URL.

        Args:
            state: A CSRF-protection state token.

        Returns:
            The authorization URL to redirect the user to.
        """
        flow = Flow.from_client_config(
            self._client_config(),
            scopes=SCOPES,
            redirect_uri=self.redirect_uri,
        )
        url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            state=state,
            prompt="consent",
        )
        return url

    def exchange_code(self, code: str) -> Credentials:
        """
        Exchange an authorization code for OAuth credentials.

        Args:
            code: The authorization code from Google's callback.

        Returns:
            The obtained Credentials object.
        """
        flow = Flow.from_client_config(
            self._client_config(),
            scopes=SCOPES,
            redirect_uri=self.redirect_uri,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        return creds

    def get_user_info(self, creds: Credentials) -> Dict[str, Any]:
        """
        Fetch the user's Google profile information (id, email, name, picture).
        """
        import httpx
        response = httpx.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"}
        )
        response.raise_for_status()
        return response.json()

    def get_credentials(self, user_id: str) -> Credentials:
        """
        Retrieve valid credentials for a user, refreshing if expired.

        Args:
            user_id: The unique user identifier.

        Returns:
            A valid Credentials object.

        Raises:
            ValueError: If no credentials exist for this user.
        """
        token_data = self.token_store.load(user_id)
        if not token_data:
            raise ValueError(
                f"No credentials for user {user_id}. They must sign in first."
            )

        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id", self.client_id),
            client_secret=token_data.get("client_secret", self.client_secret),
            scopes=token_data.get("scopes", SCOPES),
        )

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self.token_store.save(user_id, creds_to_dict(creds))
                logger.info(f"Refreshed OAuth token for user {user_id}")
            except Exception as e:
                logger.error(f"Token refresh failed for user {user_id}: {e}")
                raise ValueError(
                    f"Session expired for user {user_id}. Please sign in again."
                ) from e

        return creds

    def get_calendar_service(self, user_id: str):
        """
        Build a Google Calendar API service for a specific user.

        Args:
            user_id: The unique user identifier.

        Returns:
            A googleapiclient Resource for the Calendar v3 API.
        """
        return build("calendar", "v3", credentials=self.get_credentials(user_id))

    def get_user_info(self, credentials: Credentials) -> dict:
        """
        Fetch the user's profile info from Google.

        Args:
            credentials: Valid OAuth credentials.

        Returns:
            Dict with 'id', 'email', 'name', 'picture' fields.
        """
        try:
            service = build("oauth2", "v2", credentials=credentials)
            user_info = service.userinfo().get().execute()
            return {
                "id": user_info.get("id", ""),
                "email": user_info.get("email", ""),
                "name": user_info.get("name", ""),
                "picture": user_info.get("picture", ""),
            }
        except Exception as e:
            logger.error(f"Failed to fetch user info: {e}")
            return {"id": "", "email": "", "name": "", "picture": ""}