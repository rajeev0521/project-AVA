import pytest
from unittest.mock import MagicMock, patch

from ava.memory.long_term_memory import LongTermMemory
from ava.memory.schemas import MemoryEntry

@pytest.fixture
def mock_supabase():
    with patch("ava.memory.long_term_memory.create_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client

@pytest.fixture
def mock_genai():
    with patch("ava.memory.long_term_memory.genai") as mock:
        mock.embed_content.return_value = {"embedding": [0.1] * 768}
        yield mock

@pytest.fixture
def memory(mock_supabase, mock_genai, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://mock-url")
    monkeypatch.setenv("SUPABASE_KEY", "mock-key")
    return LongTermMemory()

def test_save_preference(memory, mock_supabase, mock_genai):
    table_mock = mock_supabase.table.return_value
    upsert_mock = table_mock.upsert.return_value
    
    success = memory.save_preference("user1", "duration", "1 hour")
    
    assert success is True
    mock_supabase.table.assert_called_with("long_term_memories")
    upsert_mock.execute.assert_called_once()
    
    args, kwargs = table_mock.upsert.call_args
    data = args[0]
    assert data["user_id"] == "user1"
    assert data["key"] == "duration"
    assert data["content"] == "1 hour"
    assert data["source"] == "user_explicit"
    assert kwargs["on_conflict"] == "user_id,key"

def test_search_preferences(memory, mock_supabase, mock_genai):
    rpc_mock = mock_supabase.rpc.return_value
    rpc_mock.execute.return_value = MagicMock(data=[
        {"id": "uuid1", "key": "duration", "content": "1 hour", "similarity": 0.9}
    ])
    
    results = memory.search_preferences("user1", "meeting length")
    
    assert len(results) == 1
    assert results[0].key == "duration"
    assert results[0].similarity == 0.9
    
    mock_supabase.rpc.assert_called_with("match_memories", {
        "query_embedding": [0.1] * 768,
        "query_user_id": "user1",
        "match_threshold": 0.75,
        "match_count": 3
    })

def test_list_preferences(memory, mock_supabase):
    table_mock = mock_supabase.table.return_value
    select_mock = table_mock.select.return_value
    eq_mock = select_mock.eq.return_value
    order_mock = eq_mock.order.return_value
    order_mock.execute.return_value = MagicMock(data=[
        {"id": "uuid1", "user_id": "user1", "key": "duration", "content": "1 hour"}
    ])
    
    results = memory.list_preferences("user1")
    assert len(results) == 1
    assert results[0].key == "duration"

def test_delete_preference(memory, mock_supabase):
    table_mock = mock_supabase.table.return_value
    delete_mock = table_mock.delete.return_value
    eq_mock1 = delete_mock.eq.return_value
    eq_mock2 = eq_mock1.eq.return_value
    
    success = memory.delete_preference("user1", "duration")
    assert success is True
    eq_mock2.execute.assert_called_once()
