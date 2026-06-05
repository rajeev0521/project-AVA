from typing import Any, Dict
from ava.tools.base_tool import BaseTool
from ava.calendar.calendar_service import CalendarManager

class CalendarToolBase(BaseTool):
    """Base class for all Calendar tools, injecting the CalendarManager."""
    def __init__(self, calendar_manager: CalendarManager):
        self.calendar_manager = calendar_manager

class CreateCalendarEventTool(CalendarToolBase):
    @property
    def name(self) -> str:
        return "create_calendar_event"
        
    @property
    def description(self) -> str:
        return "Create a new event on Google Calendar."
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title of the event"},
                "start_time": {"type": "string", "description": "ISO 8601 start time"},
                "end_time": {"type": "string", "description": "ISO 8601 end time"},
                "description": {"type": "string", "description": "Optional description of the event"},
                "location": {"type": "string", "description": "Optional location of the event"}
            },
            "required": ["title", "start_time", "end_time"]
        }
        
    async def execute(self, **kwargs) -> Any:
        return self.calendar_manager.execute_command("create_event", kwargs)

class ReadCalendarEventsTool(CalendarToolBase):
    @property
    def name(self) -> str:
        return "read_calendar_events"
        
    @property
    def description(self) -> str:
        return "Read events from Google Calendar for a specific date or time range."
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_time": {"type": "string", "description": "Optional ISO 8601 start time. If missing, defaults to today."},
                "end_time": {"type": "string", "description": "Optional ISO 8601 end time."}
            },
            "required": []
        }
        
    async def execute(self, **kwargs) -> Any:
        return self.calendar_manager.execute_command("read_events", kwargs)

class UpdateCalendarEventTool(CalendarToolBase):
    @property
    def name(self) -> str:
        return "update_calendar_event"
        
    @property
    def description(self) -> str:
        return "Update an existing calendar event."
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title of the event to update"},
                "start_time": {"type": "string", "description": "New ISO 8601 start time"},
                "end_time": {"type": "string", "description": "New ISO 8601 end time"},
                "description": {"type": "string", "description": "New description"},
                "location": {"type": "string", "description": "New location"}
            },
            "required": ["title"]
        }
        
    async def execute(self, **kwargs) -> Any:
        return self.calendar_manager.execute_command("update_event", kwargs)

class DeleteCalendarEventTool(CalendarToolBase):
    @property
    def name(self) -> str:
        return "delete_calendar_event"
        
    @property
    def description(self) -> str:
        return "Delete a calendar event."
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The title of the event to delete"},
                "date": {"type": "string", "description": "Optional date of the event in ISO format"}
            },
            "required": ["title"]
        }
        
    async def execute(self, **kwargs) -> Any:
        return self.calendar_manager.execute_command("delete_event", kwargs)
