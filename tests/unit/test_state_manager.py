import pytest
import time
from ava.conversation.state_manager import SessionManager

def test_session_manager_create_and_get():
    manager = SessionManager(max_sessions=2, ttl_seconds=10)
    session1 = manager.create_session("user1")
    
    assert session1.user_id == "user1"
    assert manager.get_session("user1") == session1
    assert manager.get_session("user_missing") is None
    
def test_session_manager_eviction():
    manager = SessionManager(max_sessions=2, ttl_seconds=10)
    manager.create_session("user1")
    manager.create_session("user2")
    
    # Exceed capacity, user1 should be evicted (LRU)
    manager.create_session("user3")
    
    assert manager.get_session("user1") is None
    assert manager.get_session("user2") is not None
    assert manager.get_session("user3") is not None

def test_session_manager_ttl():
    manager = SessionManager(max_sessions=2, ttl_seconds=0.1)
    manager.create_session("user1")
    
    time.sleep(0.2)
    
    assert manager.get_session("user1") is None

def test_session_manager_stats():
    manager = SessionManager(max_sessions=5, ttl_seconds=10)
    manager.create_session("user1")
    manager.create_session("user2")
    
    stats = manager.get_stats()
    assert stats["active_sessions"] == 2
    assert stats["max_sessions"] == 5
