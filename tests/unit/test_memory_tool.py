import pytest
from unittest.mock import MagicMock

from ava.tools.memory_tool import SaveUserPreferenceTool, ListUserPreferencesTool, DeleteUserPreferenceTool
from ava.memory.schemas import MemoryEntry

@pytest.fixture
def mock_ltm():
    return MagicMock()

@pytest.fixture
def mock_session(mock_ltm):
    session = MagicMock()
    session.user_id = "user1"
    session.memory_manager = mock_ltm
    return session

@pytest.mark.asyncio
async def test_save_preference_tool(mock_session):
    tool = SaveUserPreferenceTool()
    mock_session.memory_manager.save_preference.return_value = True
    
    result = await tool.execute(session=mock_session, key="duration", content="1 hour")
    
    assert result["status"] == "success"
    mock_session.memory_manager.save_preference.assert_called_once_with("user1", "duration", "1 hour")

@pytest.mark.asyncio
async def test_list_preferences_tool(mock_session):
    tool = ListUserPreferencesTool()
    mock_session.memory_manager.list_preferences.return_value = [
        MemoryEntry(user_id="user1", key="duration", content="1 hour")
    ]
    
    result = await tool.execute(session=mock_session)
    
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["preferences"][0]["key"] == "duration"

@pytest.mark.asyncio
async def test_delete_preference_tool(mock_session):
    tool = DeleteUserPreferenceTool()
    mock_session.memory_manager.delete_preference.return_value = True
    
    result = await tool.execute(session=mock_session, key="duration")
    
    assert result["status"] == "success"
    mock_session.memory_manager.delete_preference.assert_called_once_with("user1", "duration")
