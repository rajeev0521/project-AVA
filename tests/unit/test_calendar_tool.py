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

@pytest.mark.asyncio
async def test_create_calendar_event_tool(mock_calendar_manager):
    tool = CreateCalendarEventTool(mock_calendar_manager)
    result = await tool.execute(title="Meeting", start_time="2026-06-03T10:00:00", end_time="2026-06-03T11:00:00")
    assert result == "Success"
    mock_calendar_manager.execute_command.assert_called_once_with("create_event", {
        "title": "Meeting",
        "start_time": "2026-06-03T10:00:00",
        "end_time": "2026-06-03T11:00:00"
    })

@pytest.mark.asyncio
async def test_read_calendar_events_tool(mock_calendar_manager):
    tool = ReadCalendarEventsTool(mock_calendar_manager)
    result = await tool.execute(start_time="2026-06-03T10:00:00")
    assert result == "Success"
    mock_calendar_manager.execute_command.assert_called_once_with("read_events", {
        "start_time": "2026-06-03T10:00:00"
    })

@pytest.mark.asyncio
async def test_update_calendar_event_tool(mock_calendar_manager):
    tool = UpdateCalendarEventTool(mock_calendar_manager)
    result = await tool.execute(title="Old Meeting", start_time="2026-06-03T11:00:00")
    assert result == "Success"
    mock_calendar_manager.execute_command.assert_called_once_with("update_event", {
        "title": "Old Meeting",
        "start_time": "2026-06-03T11:00:00"
    })

@pytest.mark.asyncio
async def test_delete_calendar_event_tool(mock_calendar_manager):
    tool = DeleteCalendarEventTool(mock_calendar_manager)
    result = await tool.execute(title="Meeting")
    assert result == "Success"
    mock_calendar_manager.execute_command.assert_called_once_with("delete_event", {
        "title": "Meeting"
    })
