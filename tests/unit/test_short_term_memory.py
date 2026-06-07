import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from ava.memory.short_term_memory import ShortTermMemory
from ava.conversation.state_manager import ConversationState
from ava.memory.schemas import SessionState

@pytest.fixture
def memory(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "http://mock-url")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "mock-token")
    mem = ShortTermMemory()
    mem.redis = MagicMock()
    return mem

@pytest.fixture
def mock_redis(memory):
    return memory.redis

@pytest.mark.asyncio
async def test_save_state(memory, mock_redis):
    state = ConversationState(session_id="user_123")
    state.turn_count = 5
    
    await memory.save_state("user_123", state)
    
    mock_redis.set.assert_called_once()
    args, kwargs = mock_redis.set.call_args
    assert args[0] == "session:user_123:state"
    assert "user_123" in args[1]
    assert kwargs["ex"] == 1800

def test_load_state_fresh(memory, mock_redis):
    saved_at = datetime.now(timezone.utc).isoformat()
    mock_redis.get.return_value = {
        "session_id": "user_123",
        "user_id": "user_123",
        "turn_count": 5,
        "saved_at": saved_at
    }
    
    state = memory.load_state("user_123")
    assert state is not None
    assert state.session_id == "user_123"
    assert state.turn_count == 5

def test_load_state_stale(memory, mock_redis):
    # Older than 4 hours
    saved_at = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    mock_redis.get.return_value = {
        "session_id": "user_123",
        "user_id": "user_123",
        "turn_count": 5,
        "saved_at": saved_at
    }
    
    state = memory.load_state("user_123")
    assert state is None
    mock_redis.delete.assert_called_once_with("session:user_123:state")

def test_delete_session(memory, mock_redis):
    memory.delete_session("user_123")
    mock_redis.delete.assert_called_once_with("session:user_123:state")
