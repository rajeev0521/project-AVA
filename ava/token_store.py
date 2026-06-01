"""
Token Store for AVA — Supabase-backed OAuth credential storage.
Provides secure per-user storage of Google OAuth refresh/access tokens.
"""

from datetime import datetime, timezone
from typing import Dict, Optional, Any

from .logger import get_logger

logger = get_logger(__name__)


class SupabaseTokenStore:
    """
    Persistent OAuth token store backed by Supabase PostgreSQL.

    Stores and retrieves Google OAuth2 credentials on a per-user basis.
    Expects a `user_tokens` table in Supabase (see supabase_schema.sql).
    """

    def __init__(self, supabase_client):
        """
        Initialize token store.

        Args:
            supabase_client: An initialized Supabase client instance.
        """
        self.db = supabase_client

    def save(self, user_id: str, creds_dict: Dict[str, Any]) -> None:
        """
        Save or update OAuth credentials for a user.

        Args:
            user_id: Unique Google user ID (sub claim).
            creds_dict: Serialized credentials dict with keys:
                        token, refresh_token, token_uri, client_id,
                        client_secret, scopes.
        """
        row = {
            "user_id": user_id,
            "token": creds_dict.get("token"),
            "refresh_token": creds_dict.get("refresh_token"),
            "token_uri": creds_dict.get("token_uri"),
            "client_id": creds_dict.get("client_id"),
            "client_secret": creds_dict.get("client_secret"),
            "scopes": list(creds_dict.get("scopes") or []),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self.db.table("user_tokens").upsert(row).execute()
            logger.info(f"Saved OAuth tokens for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save tokens for user {user_id}: {e}")
            raise

    def load(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Load OAuth credentials for a user.

        Args:
            user_id: Unique Google user ID.

        Returns:
            Dict with credential fields, or None if not found.
        """
        try:
            result = (
                self.db.table("user_tokens")
                .select("token, refresh_token, token_uri, client_id, client_secret, scopes")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            if result.data:
                logger.debug(f"Loaded OAuth tokens for user {user_id}")
                return result.data
            return None
        except Exception as e:
            logger.error(f"Failed to load tokens for user {user_id}: {e}")
            return None

    def delete(self, user_id: str) -> None:
        """
        Delete stored credentials for a user (e.g., on logout/revoke).

        Args:
            user_id: Unique Google user ID.
        """
        try:
            self.db.table("user_tokens").delete().eq("user_id", user_id).execute()
            logger.info(f"Deleted OAuth tokens for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to delete tokens for user {user_id}: {e}")

    def exists(self, user_id: str) -> bool:
        """
        Check if credentials exist for a user.

        Args:
            user_id: Unique Google user ID.

        Returns:
            True if credentials are stored.
        """
        try:
            result = (
                self.db.table("user_tokens")
                .select("user_id")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            return result.data is not None
        except Exception:
            return False


class NullTokenStore:
    """
    Null Object pattern implementation of the token store interface.

    Used in environments where Supabase is not configured (e.g., desktop mode,
    local development). All operations are safe no-ops.
    """

    def save(self, user_id: str, creds_dict: Dict[str, Any]) -> None:
        logger.debug(f"NullTokenStore: save called for user {user_id} (no-op)")

    def load(self, user_id: str) -> Optional[Dict[str, Any]]:
        return None

    def delete(self, user_id: str) -> None:
        logger.debug(f"NullTokenStore: delete called for user {user_id} (no-op)")

    def exists(self, user_id: str) -> bool:
        return False
