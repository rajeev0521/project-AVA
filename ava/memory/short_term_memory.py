import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from ava.logger import get_logger
from ava.memory.schemas import SessionState
from ava.conversation.state_manager import ConversationState

logger = get_logger(__name__)

class ShortTermMemory:
    """
    Backs up ConversationState to Upstash Redis for restore-on-restart.
    Supplements the in-process state to provide session recovery.
    """
    
    def __init__(self, ttl_seconds: int = 1800):
        self.ttl_seconds = ttl_seconds
        self.redis = None
        self._init_redis()
        
    def _init_redis(self):
        try:
            from upstash_redis import Redis
            url = os.environ.get("UPSTASH_REDIS_REST_URL")
            token = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
            if url and token:
                self.redis = Redis(url=url, token=token)
                logger.info("Upstash Redis client initialized successfully.")
            else:
                logger.warning("Upstash Redis credentials missing. ShortTermMemory is disabled.")
        except ImportError:
            logger.warning("upstash-redis not installed. ShortTermMemory is disabled.")
        except Exception as e:
            logger.warning(f"Failed to initialize Upstash Redis: {e}")

    async def save_state(self, session_id: str, state: ConversationState) -> None:
        """Asynchronously serialize state and write to Redis."""
        if not self.redis:
            return
            
        try:
            # Snapshot the state into our schema
            snapshot = SessionState(
                session_id=session_id,
                user_id=state.session_id, # In our app, session_id == user_id
                pending_action=state.pending_action,
                missing_fields=state.missing_fields,
                draft_event=state.draft_event,
                last_event=state.last_event,
                turn_count=state.turn_count,
                saved_at=datetime.now(timezone.utc).isoformat()
            )
            
            key = f"session:{session_id}:state"
            # upstash_redis supports synchronous calls which can block, but if we have async client
            # The async client is `from upstash_redis.asyncio import Redis`
            # For simplicity, if we are using the sync client here, it's HTTP based so it's fast.
            # Let's import the async client if possible, but the standard Redis from upstash_redis handles sync.
            # In AssistantBrain, we'll wrap this in run_in_executor or create_task.
            self.redis.set(key, snapshot.model_dump_json(), ex=self.ttl_seconds)
            logger.debug(f"Saved session state for {session_id} to Redis.")
        except Exception as e:
            logger.warning(f"Failed to save state to Redis: {e}")

    def load_state(self, session_id: str) -> Optional[ConversationState]:
        """Deserialize from Redis. Delete if older than 4 hours."""
        if not self.redis:
            return None
            
        try:
            key = f"session:{session_id}:state"
            data = self.redis.get(key)
            if not data:
                return None
                
            if isinstance(data, str):
                snapshot = SessionState.model_validate_json(data)
            else:
                snapshot = SessionState(**data)
                
            saved_at = datetime.fromisoformat(snapshot.saved_at)
            age = datetime.now(timezone.utc) - saved_at
            
            if age > timedelta(hours=4):
                logger.info(f"Session {session_id} state is stale (>4 hours). Discarding.")
                self.delete_session(session_id)
                return None
                
            # Reconstruct ConversationState
            state = ConversationState(session_id=snapshot.session_id)
            state.pending_action = snapshot.pending_action
            state.missing_fields = snapshot.missing_fields
            state.draft_event = snapshot.draft_event
            state.last_event = snapshot.last_event
            state.turn_count = snapshot.turn_count
            
            logger.info(f"Loaded session state for {session_id} from Redis.")
            return state
        except Exception as e:
            logger.warning(f"Failed to load state from Redis: {e}")
            return None

    def delete_session(self, session_id: str) -> None:
        """Deletes all keys for a session."""
        if not self.redis:
            return
            
        try:
            key = f"session:{session_id}:state"
            self.redis.delete(key)
            logger.debug(f"Deleted session state for {session_id} from Redis.")
        except Exception as e:
            logger.warning(f"Failed to delete session state from Redis: {e}")
