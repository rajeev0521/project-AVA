"""
Session Manager for AVA.
Manages user sessions in memory with LRU + TTL eviction to prevent memory leaks.
Ready to be swapped with Redis in a multi-instance deployment.
"""

import time
import threading
from collections import OrderedDict
from typing import Dict, Any, Optional

from .logger import get_logger

logger = get_logger(__name__)


class UserSession:
    """Represents an active user session."""
    
    def __init__(self, user_id: str, memory_manager=None, calendar_manager=None):
        self.user_id = user_id
        self.memory_manager = memory_manager
        self.calendar_manager = calendar_manager
        
        # State machine for complex interactions (like bulk delete confirmation)
        self.awaiting_confirmation = False
        self.pending_action = None
        self.pending_data = None
        
        # Last active timestamp for TTL eviction
        self.last_active = time.monotonic()


class SessionManager:
    """
    In-memory session manager with LRU and TTL eviction.
    Thread-safe.
    """
    
    def __init__(self, max_sessions: int = 100, ttl_seconds: int = 1800):
        """
        Initialize the session manager.
        
        Args:
            max_sessions: Maximum number of active sessions to keep in memory.
            ttl_seconds: Time-to-live for a session in seconds (default 30 mins).
        """
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        
        self._sessions: OrderedDict[str, UserSession] = OrderedDict()
        self._lock = threading.Lock()
        
        logger.info(f"SessionManager initialized (max={max_sessions}, ttl={ttl_seconds}s)")
    
    def get_session(self, user_id: str) -> Optional[UserSession]:
        """
        Get an active session for the user, updating its last_active time.
        Returns None if no session exists or if it has expired.
        """
        with self._lock:
            self._evict_expired_nolock()
            
            if user_id in self._sessions:
                session = self._sessions.pop(user_id)
                session.last_active = time.monotonic()
                self._sessions[user_id] = session  # Move to end (most recently used)
                return session
            return None
    
    def create_session(self, user_id: str, memory_manager, calendar_manager) -> UserSession:
        """
        Create a new session, evicting oldest if max_sessions is reached.
        """
        with self._lock:
            self._evict_expired_nolock()
            
            # If already exists, just update its managers and move to end
            if user_id in self._sessions:
                session = self._sessions.pop(user_id)
                session.memory_manager = memory_manager
                session.calendar_manager = calendar_manager
                session.last_active = time.monotonic()
            else:
                # Evict LRU if at capacity
                if len(self._sessions) >= self.max_sessions:
                    lru_id, _ = self._sessions.popitem(last=False)
                    logger.info(f"Evicted LRU session for user {lru_id}")
                
                session = UserSession(
                    user_id=user_id,
                    memory_manager=memory_manager,
                    calendar_manager=calendar_manager
                )
            
            self._sessions[user_id] = session
            logger.info(f"Created/Updated session for user {user_id}")
            return session
    
    def _evict_expired_nolock(self):
        """Evict expired sessions (must be called with _lock held)."""
        now = time.monotonic()
        expired_keys = []
        
        for user_id, session in self._sessions.items():
            if now - session.last_active > self.ttl_seconds:
                expired_keys.append(user_id)
        
        for key in expired_keys:
            self._sessions.pop(key)
            logger.debug(f"Evicted expired session for user {key}")
            
    def get_stats(self) -> Dict[str, Any]:
        """Return session statistics."""
        with self._lock:
            self._evict_expired_nolock()
            return {
                "active_sessions": len(self._sessions),
                "max_sessions": self.max_sessions,
                "ttl_seconds": self.ttl_seconds
            }
