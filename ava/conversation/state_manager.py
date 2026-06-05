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

class UserSession:
    """Represents an active user session."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.conversation_state = ConversationState(session_id=user_id)
        self.chat_session = None  # Holds genai.ChatSession
        
        # Last active timestamp for TTL eviction
        self.last_active = time.monotonic()

class SessionManager:
    """
    In-memory session manager with LRU and TTL eviction.
    Thread-safe.
    """
    
    def __init__(self, max_sessions: int = 100, ttl_seconds: int = 1800):
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        
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
            return None
    
    def create_session(self, user_id: str) -> UserSession:
        with self._lock:
            self._evict_expired_nolock()
            
            if user_id in self._sessions:
                session = self._sessions.pop(user_id)
                session.last_active = time.monotonic()
            else:
                if len(self._sessions) >= self.max_sessions:
                    lru_id, _ = self._sessions.popitem(last=False)
                    logger.info(f"Evicted LRU session for user {lru_id}")
                
                session = UserSession(user_id=user_id)
            
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
