from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    """
    Centralized configuration for AVA using pydantic-settings.
    Validates environment variables on startup.
    """
    
    # Supabase (Optional)
    supabase_url: str = ""
    supabase_key: str = ""
    
    # Gemini
    gemini_api_key: str
    
    # Google OAuth
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    
    # CORS
    cors_origins: List[str] = ["http://localhost:8000"]
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate a global config object
try:
    config = Settings()
except Exception as e:
    import logging
    logger = logging.getLogger("ava.config")
    logger.error(f"Configuration error: {e}")
    # Allow the application to start for testing purposes if env is missing,
    # but actual features relying on API keys will fail later.
    config = Settings(
        gemini_api_key="missing",
        google_client_id="missing",
        google_client_secret="missing"
    )
