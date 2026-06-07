import pytest
from unittest.mock import MagicMock
from ava.tools.calendar_tool import (
    CreateCalendarEventTool, 
    ReadCalendarEventsTool, 
    UpdateCalendarEventTool, 
    DeleteCalendarEventTool
)

@pytest.fixture
def mock_calendar_manager():
    manager = MagicMock()
    manager.execute_command.return_value = "Success"
    return manager

@pytest.fixture
def mock_session(mock_calendar_manager):
    session = MagicMock()
    session.calendar_manager = mock_calendar_manager
    return session

@pytest.mark.asyncio
async def test_create_calendar_event_tool(mock_session):
    tool = CreateCalendarEventTool()
    result = await tool.execute(session=mock_session, title="Meeting", start_time="2026-06-03T10:00:00", end_time="2026-06-03T11:00:00")
    assert result == "Success"
    mock_session.calendar_manager.execute_command.assert_called_once_with("create_event", {
        "title": "Meeting",
        "start_time": "2026-06-03T10:00:00",
        "end_time": "2026-06-03T11:00:00"
    })

@pytest.mark.asyncio
async def test_read_calendar_events_tool(mock_session):
    tool = ReadCalendarEventsTool()
    result = await tool.execute(session=mock_session, start_time="2026-06-03T10:00:00")
    assert result == "Success"
    mock_session.calendar_manager.execute_command.assert_called_once_with("read_events", {
        "start_time": "2026-06-03T10:00:00"
    })

@pytest.mark.asyncio
async def test_update_calendar_event_tool(mock_session):
    tool = UpdateCalendarEventTool()
    result = await tool.execute(session=mock_session, title="Old Meeting", start_time="2026-06-03T11:00:00")
    assert result == "Success"
    mock_session.calendar_manager.execute_command.assert_called_once_with("update_event", {
        "title": "Old Meeting",
        "start_time": "2026-06-03T11:00:00"
    })

@pytest.mark.asyncio
async def test_delete_calendar_event_tool(mock_session):
    tool = DeleteCalendarEventTool()
    result = await tool.execute(session=mock_session, title="Meeting")
    assert result == "Success"
    mock_session.calendar_manager.execute_command.assert_called_once_with("delete_event", {
        "title": "Meeting"
    })
