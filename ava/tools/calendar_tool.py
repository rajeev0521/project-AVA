from typing import Any, Dict
from ava.tools.base_tool import BaseTool
from ava.calendar.calendar_service import CalendarManager

from ava.conversation.event_resolver import EventResolver

class CalendarToolBase(BaseTool):
    """Base class for all Calendar tools."""
    def _get_manager(self, session):
        if not session or not hasattr(session, "calendar_manager") or not session.calendar_manager:
            raise ValueError("Calendar manager not initialized. Please sign in with Google.")
        return session.calendar_manager

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
        
    async def execute(self, session, **kwargs) -> Any:
        try:
            manager = self._get_manager(session)
            return manager.execute_command("create_event", kwargs)
        except Exception as e:
            return {"error": f"Failed to create event: {str(e)}"}

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
        
    async def execute(self, session, **kwargs) -> Any:
        try:
            manager = self._get_manager(session)
            return manager.execute_command("read_events", kwargs)
        except Exception as e:
            return {"error": f"Failed to read events: {str(e)}"}

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
        
    async def execute(self, session, **kwargs) -> Any:
        try:
            manager = self._get_manager(session)
            return manager.execute_command("update_event", kwargs)
        except Exception as e:
            return {"error": f"Failed to update event: {str(e)}"}

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
        
    async def execute(self, session, **kwargs) -> Any:
        try:
            manager = self._get_manager(session)
            return manager.execute_command("delete_event", kwargs)
        except Exception as e:
            return {"error": f"Failed to delete event: {str(e)}"}


# ─── Phase 4: Semantic Event Resolution Tools ──────────────────────────────


class ResolveCalendarEventTool(CalendarToolBase):
    """
    Tool for Gemini to resolve ambiguous event references.

    When the user says things like "move it", "delete that meeting",
    or "update tomorrow's event", this tool resolves the reference
    to a specific calendar event.
    """

    @property
    def name(self) -> str:
        return "resolve_calendar_event"

    @property
    def description(self) -> str:
        return (
            "Resolve a vague or ambiguous event reference to a specific calendar event. "
            "Use this when the user refers to an event by pronoun ('it', 'that one'), "
            "partial name ('the project meet'), temporal hint ('tomorrow's meeting'), "
            "or contextual reference ('the one we discussed'). "
            "Returns the resolved event's ID, title, and time."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": (
                        "The user's event reference to resolve. Examples: "
                        "'it', 'that meeting', 'tomorrow\\'s event', 'project discussion'"
                    ),
                },
                "date_hint": {
                    "type": "string",
                    "description": (
                        "Optional ISO date string to narrow search. "
                        "E.g., '2026-06-05' if the user said 'tomorrow'."
                    ),
                },
            },
            "required": ["reference"],
        }

    async def execute(self, session, **kwargs) -> Any:
        reference = kwargs.get("reference", "")
        date_hint = kwargs.get("date_hint")

        try:
            manager = self._get_manager(session)
            resolver = EventResolver(manager)
            
            # We need a conversation state
            conversation_state = getattr(session, "conversation_state", None)

            result = await resolver.resolve(
                reference=reference,
                conversation_state=conversation_state,
                date_hint=date_hint,
            )

            if result:
                return {
                    "resolved": True,
                    "event_id": result.event_id,
                    "title": result.title,
                    "start": result.start,
                    "end": result.end,
                    "strategy": result.strategy,
                    "confidence": result.confidence,
                }
            else:
                return {
                    "resolved": False,
                    "message": f"Could not find an event matching '{reference}'. "
                    "Please provide a more specific event name or date.",
                }
        except Exception as e:
            return {"error": f"Resolution failed: {str(e)}"}


class FindCalendarEventTool(CalendarToolBase):
    """
    Tool for finding calendar events by a search query.

    Unlike ResolveCalendarEventTool (which tries to find THE single best match),
    this tool returns multiple matching events — useful for disambiguation
    or when the user wants to browse matching events.
    """

    @property
    def name(self) -> str:
        return "find_calendar_event"

    @property
    def description(self) -> str:
        return (
            "Search for calendar events matching a query. Returns multiple results "
            "ranked by relevance. Use this when you need to find events by name, "
            "date, or partial description before performing an update or delete."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — event title, partial name, or description.",
                },
                "date_hint": {
                    "type": "string",
                    "description": "Optional ISO date string to narrow the search window.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, session, **kwargs) -> Any:
        query = kwargs.get("query", "")
        date_hint = kwargs.get("date_hint")
        max_results = int(kwargs.get("max_results", 5))

        try:
            manager = self._get_manager(session)
            resolver = EventResolver(manager)
            conversation_state = getattr(session, "conversation_state", None)

            results = await resolver.resolve_all(
                reference=query,
                conversation_state=conversation_state,
                date_hint=date_hint,
                max_results=max_results,
            )

            if results:
                return {
                    "found": True,
                    "count": len(results),
                    "events": [r.to_dict() for r in results],
                }
            else:
                return {
                    "found": False,
                    "count": 0,
                    "events": [],
                    "message": f"No events found matching '{query}'.",
                }
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}
