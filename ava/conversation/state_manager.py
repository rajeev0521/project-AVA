import time
import threading
from collections import OrderedDict
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from ava.logger import get_logger

logger = get_logger(__name__)

@dataclass
class ConversationState:
    session_id: str
    pending_action: Optional[str] = None
    missing_fields: List[str] = field(default_factory=list)
    draft_event: Optional[dict] = None
    last_event: Optional[Any] = None
    last_query: Optional[str] = None
    turn_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Phase 4: Semantic Event Resolution — track recently mentioned events
    # and conversation history for contextual reference resolution
    last_mentioned_events: List[dict] = field(default_factory=list)
    conversation_history: List[dict] = field(default_factory=list)

    # Max items to retain
    MAX_MENTIONED_EVENTS: int = field(default=5, repr=False)
    MAX_HISTORY_TURNS: int = field(default=20, repr=False)

    def track_event(self, event: dict) -> None:
        """
        Record an event as recently mentioned in the conversation.
        Also updates last_event. Keeps at most MAX_MENTIONED_EVENTS entries.
        """
        if not event:
            return

        self.last_event = event
        self.last_mentioned_events.append(event)
        if len(self.last_mentioned_events) > self.MAX_MENTIONED_EVENTS:
            self.last_mentioned_events = self.last_mentioned_events[
                -self.MAX_MENTIONED_EVENTS :
            ]
        self.updated_at = datetime.now()

    def add_turn(self, role: str, content: str, metadata: Optional[dict] = None) -> None:
        """
        Append a conversation turn to history.
        Keeps at most MAX_HISTORY_TURNS entries.
        """
        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        if metadata:
            turn["metadata"] = metadata

        self.conversation_history.append(turn)
        if len(self.conversation_history) > self.MAX_HISTORY_TURNS:
            self.conversation_history = self.conversation_history[
                -self.MAX_HISTORY_TURNS :
            ]
        self.updated_at = datetime.now()

class UserSession:
    """Represents an active user session."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.conversation_state = ConversationState(session_id=user_id)
        self.chat_session = None  # Holds genai.ChatSession
        
        # Last active timestamp for TTL eviction
        self.last_active = time.monotonic()

    def update_last_event(self, event_data: Any) -> None:
        """
        Convenience method to update the last_event on the conversation state.
        Parses common event formats from calendar tool responses.
        """
        if not event_data:
            return

        if isinstance(event_data, dict):
            self.conversation_state.track_event(event_data)
        elif isinstance(event_data, str):
            # Try to extract event info from a string response — limited,
            # but at least store the raw text as metadata
            logger.debug(f"Received string event data, storing as last_query context")

class SessionManager:
    """
    In-memory session manager with LRU and TTL eviction.
    Thread-safe.
    """
    
    def __init__(self, max_sessions: int = 100, ttl_seconds: int = 1800, short_term_memory=None):
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self.short_term_memory = short_term_memory
        
        self._sessions: OrderedDict[str, UserSession] = OrderedDict()
        self._lock = threading.Lock()
        
        logger.info(f"SessionManager initialized (max={max_sessions}, ttl={ttl_seconds}s)")
    
    def get_session(self, user_id: str) -> Optional[UserSession]:
        with self._lock:
            self._evict_expired_nolock()
            
            if user_id in self._sessions:
                session = self._sessions.pop(user_id)
                session.last_active = time.monotonic()
                self._sessions[user_id] = session  # Move to end (most recently used)
                return session
            
            # If not in memory, try restoring from Redis ShortTermMemory
            if self.short_term_memory:
                state = self.short_term_memory.load_state(user_id)
                if state:
                    session = UserSession(user_id=user_id)
                    session.conversation_state = state
                    
                    # Evict if full
                    if len(self._sessions) >= self.max_sessions:
                        lru_id, _ = self._sessions.popitem(last=False)
                        logger.info(f"Evicted LRU session for user {lru_id}")
                        
                    self._sessions[user_id] = session
                    return session

            return None
    
    def create_session(self, user_id: str) -> UserSession:
        with self._lock:
            self._evict_expired_nolock()
            
            if user_id in self._sessions:
                session = self._sessions.pop(user_id)
                session.last_active = time.monotonic()
            else:
                # Evict if full before creating new
                if len(self._sessions) >= self.max_sessions:
                    lru_id, _ = self._sessions.popitem(last=False)
                    logger.info(f"Evicted LRU session for user {lru_id}")
                
                session = UserSession(user_id=user_id)
                
                # Check if we can restore state
                if self.short_term_memory:
                    state = self.short_term_memory.load_state(user_id)
                    if state:
                        session.conversation_state = state
                        logger.info(f"Restored session state for {user_id} from Redis.")
            
            self._sessions[user_id] = session
            logger.info(f"Created/Updated session for user {user_id}")
            return session
    
    def _evict_expired_nolock(self):
        now = time.monotonic()
        expired_keys = [k for k, v in self._sessions.items() if now - v.last_active > self.ttl_seconds]
        for key in expired_keys:
            self._sessions.pop(key)
            logger.debug(f"Evicted expired session for user {key}")
            
    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            self._evict_expired_nolock()
            return {
                "active_sessions": len(self._sessions),
                "max_sessions": self.max_sessions,
                "ttl_seconds": self.ttl_seconds
            }
