import os
from typing import List, Optional
import google.generativeai as genai
from supabase import create_client, Client

from ava.logger import get_logger
from ava.memory.schemas import MemoryEntry

logger = get_logger(__name__)

class LongTermMemory:
    """
    Manages persistent user preferences in Supabase with pgvector similarity search.
    All writes are upserts via UNIQUE(user_id, key).
    """
    
    def __init__(self, embedding_model: str = "models/text-embedding-004"):
        self.embedding_model = embedding_model
        self.supabase: Optional[Client] = None
        self._init_supabase()
        
    def _init_supabase(self):
        try:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_KEY")
            if url and key:
                self.supabase = create_client(url, key)
                logger.info("Supabase client initialized for LongTermMemory.")
            else:
                logger.warning("Supabase credentials missing. LongTermMemory is disabled.")
        except Exception as e:
            logger.warning(f"Failed to initialize Supabase: {e}")

    def _embed(self, text: str) -> List[float]:
        """Generate embedding using Gemini."""
        try:
            result = genai.embed_content(
                model=self.embedding_model,
                content=text,
                task_type="retrieval_document"
            )
            return result['embedding']
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return []

    def save_preference(self, user_id: str, key: str, content: str) -> bool:
        """
        Upserts a preference into long_term_memories.
        Overwrites any existing preference with the same key.
        """
        if not self.supabase:
            return False
            
        embedding = self._embed(content)
        if not embedding:
            return False
            
        try:
            data = {
                "user_id": user_id,
                "key": key,
                "content": content,
                "embedding": embedding,
                "embedding_model": "text-embedding-004",
                "source": "user_explicit"
            }
            # The migration created UNIQUE(user_id, key)
            self.supabase.table("long_term_memories").upsert(data, on_conflict="user_id,key").execute()
            logger.info(f"Saved preference for {user_id} with key '{key}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to save preference to Supabase: {e}")
            return False

    def search_preferences(self, user_id: str, query: str, match_threshold: float = 0.75) -> List[MemoryEntry]:
        """
        Search for preferences related to the query using the match_memories RPC.
        Returns up to 3 MemoryEntry objects with similarity >= match_threshold.
        """
        if not self.supabase:
            return []
            
        embedding = self._embed(query)
        if not embedding:
            return []
            
        try:
            # Call the RPC created in migration
            response = self.supabase.rpc("match_memories", {
                "query_embedding": embedding,
                "query_user_id": user_id,
                "match_threshold": match_threshold,
                "match_count": 3
            }).execute()
            
            entries = []
            if response.data:
                for row in response.data:
                    entries.append(MemoryEntry(
                        id=row.get("id"),
                        user_id=user_id,
                        key=row.get("key"),
                        content=row.get("content"),
                        similarity=row.get("similarity")
                    ))
            return entries
        except Exception as e:
            logger.error(f"Failed to search preferences in Supabase: {e}")
            return []

    def list_preferences(self, user_id: str) -> List[MemoryEntry]:
        """Returns all stored preferences for a user."""
        if not self.supabase:
            return []
            
        try:
            response = self.supabase.table("long_term_memories").select("id, user_id, key, content, created_at, updated_at").eq("user_id", user_id).order("updated_at", desc=True).execute()
            entries = []
            if response.data:
                for row in response.data:
                    entries.append(MemoryEntry(**row))
            return entries
        except Exception as e:
            logger.error(f"Failed to list preferences: {e}")
            return []

    def delete_preference(self, user_id: str, key: str) -> bool:
        """Deletes a single preference by key."""
        if not self.supabase:
            return False
            
        try:
            self.supabase.table("long_term_memories").delete().eq("user_id", user_id).eq("key", key).execute()
            logger.info(f"Deleted preference '{key}' for user {user_id}.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete preference: {e}")
            return False
