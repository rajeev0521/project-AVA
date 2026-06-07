"""
Scheduling Intelligence for AVA 2.0

Provides conflict detection, free-slot discovery, and smart alternative
suggestions. Works against Google Calendar via CalendarManager.

Gemini tool classes:
- CheckConflictsTool   — detect conflicts for a proposed time window
- FindFreeSlotsTool    — discover available windows on a given date
- SuggestAlternativesTool — suggest ranked alternatives near a conflicting slot
"""

from datetime import datetime, timedelta, time as dt_time
from typing import Any, Dict, List, Optional, Tuple

from ava.tools.base_tool import BaseTool
from ava.logger import get_logger

logger = get_logger(__name__)


# ─── Data structures ────────────────────────────────────────────────────────


class TimeSlot:
    """Represents an available time window."""

    def __init__(self, start: datetime, end: datetime, score: float = 1.0):
        self.start = start
        self.end = end
        self.score = score  # 0–1, higher = more preferred

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": self.duration_minutes,
            "score": round(self.score, 2),
        }

    def __repr__(self) -> str:
        return (
            f"TimeSlot({self.start.strftime('%H:%M')}–"
            f"{self.end.strftime('%H:%M')}, {self.duration_minutes}min)"
        )


class ConflictInfo:
    """Represents a scheduling conflict."""

    def __init__(
        self,
        event_id: str,
        title: str,
        start: datetime,
        end: datetime,
        overlap_minutes: int = 0,
    ):
        self.event_id = event_id
        self.title = title
        self.start = start
        self.end = end
        self.overlap_minutes = overlap_minutes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "overlap_minutes": self.overlap_minutes,
        }


# ─── Core Scheduler Service ────────────────────────────────────────────────


class SchedulerService:
    """
    Core scheduling intelligence — pure logic, no Gemini schema concerns.

    Consumed by the tool wrappers below and directly by CalendarManager
    if needed.
    """

    def __init__(self, calendar_manager: Any):
        self.calendar_manager = calendar_manager

    # ── Conflict Detection ──────────────────────────────────────────────

    def check_conflicts(
        self, start: datetime, end: datetime
    ) -> List[ConflictInfo]:
        """
        Return all events that overlap with the proposed [start, end) window.
        """
        service = self.calendar_manager._get_calendar_service()
        if not service:
            logger.warning("No calendar service for conflict check")
            return []

        try:
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=self._fmt(start),
                    timeMax=self._fmt(end),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            conflicts: List[ConflictInfo] = []
            for ev in events_result.get("items", []):
                ev_start = self._parse_event_dt(ev, "start")
                ev_end = self._parse_event_dt(ev, "end")
                if ev_start is None or ev_end is None:
                    continue

                overlap = self._overlap_minutes(start, end, ev_start, ev_end)
                if overlap > 0:
                    conflicts.append(
                        ConflictInfo(
                            event_id=ev.get("id", ""),
                            title=ev.get("summary", "Untitled"),
                            start=ev_start,
                            end=ev_end,
                            overlap_minutes=overlap,
                        )
                    )

            return conflicts

        except Exception as e:
            logger.error(f"Conflict check failed: {e}")
            return []

    # ── Free-Slot Discovery ─────────────────────────────────────────────

    def find_free_slots(
        self,
        date: datetime,
        duration_minutes: int = 30,
        working_hours: Tuple[str, str] = ("09:00", "21:00"),
    ) -> List[TimeSlot]:
        """
        Find all free time windows of at least `duration_minutes` on `date`
        within the given working-hours range.
        """
        service = self.calendar_manager._get_calendar_service()
        if not service:
            logger.warning("No calendar service for free-slot search")
            return []

        tz = self.calendar_manager.local_tz

        # Build day boundaries from working_hours
        wh_start = self._time_from_str(working_hours[0])
        wh_end = self._time_from_str(working_hours[1])

        day_start = date.replace(
            hour=wh_start.hour, minute=wh_start.minute, second=0, microsecond=0
        )
        day_end = date.replace(
            hour=wh_end.hour, minute=wh_end.minute, second=0, microsecond=0
        )

        # Ensure timezone
        if day_start.tzinfo is None:
            if hasattr(tz, "localize"):
                day_start = tz.localize(day_start)
                day_end = tz.localize(day_end)
            else:
                day_start = day_start.replace(tzinfo=tz)
                day_end = day_end.replace(tzinfo=tz)

        try:
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=day_start.isoformat(),
                    timeMax=day_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )

            busy_intervals = []
            for ev in events_result.get("items", []):
                ev_start = self._parse_event_dt(ev, "start")
                ev_end = self._parse_event_dt(ev, "end")
                if ev_start and ev_end:
                    busy_intervals.append((ev_start, ev_end))

            # Sort by start time
            busy_intervals.sort(key=lambda x: x[0])

            return self._extract_free_slots(
                day_start, day_end, busy_intervals, duration_minutes
            )

        except Exception as e:
            logger.error(f"Free-slot search failed: {e}")
            return []

    # ── Alternative Suggestions ─────────────────────────────────────────

    def suggest_alternatives(
        self,
        conflicting_start: datetime,
        duration_minutes: int,
        max_suggestions: int = 3,
        working_hours: Tuple[str, str] = ("09:00", "21:00"),
    ) -> List[TimeSlot]:
        """
        Given a conflicting time slot, suggest the next `max_suggestions`
        available windows of the requested duration, searching the same day
        first and then the next day if needed.

        Slots are ranked by proximity to the originally requested time.
        """
        suggestions: List[TimeSlot] = []

        # Search same day first, then next day
        for day_offset in range(3):  # today, tomorrow, day after
            search_date = conflicting_start + timedelta(days=day_offset)
            free = self.find_free_slots(
                search_date, duration_minutes, working_hours
            )

            for slot in free:
                # Skip slots that start before the conflicting start (same day)
                if day_offset == 0 and slot.start < conflicting_start:
                    continue

                # Score by proximity: closer to original time = higher score
                hours_diff = abs(
                    (slot.start - conflicting_start).total_seconds() / 3600
                )
                score = max(0.1, 1.0 - (hours_diff * 0.1))
                slot.score = score
                suggestions.append(slot)

                if len(suggestions) >= max_suggestions:
                    break

            if len(suggestions) >= max_suggestions:
                break

        # Sort by score descending
        suggestions.sort(key=lambda s: s.score, reverse=True)
        return suggestions[:max_suggestions]

    # ── Internal Helpers ────────────────────────────────────────────────

    def _extract_free_slots(
        self,
        day_start: datetime,
        day_end: datetime,
        busy_intervals: List[Tuple[datetime, datetime]],
        min_duration_minutes: int,
    ) -> List[TimeSlot]:
        """
        Subtract busy intervals from [day_start, day_end] and return
        gaps that are at least `min_duration_minutes` long.
        """
        min_duration = timedelta(minutes=min_duration_minutes)
        free_slots: List[TimeSlot] = []

        cursor = day_start

        for busy_start, busy_end in busy_intervals:
            # Clamp to working hours
            busy_start = max(busy_start, day_start)
            busy_end = min(busy_end, day_end)

            if cursor < busy_start:
                gap = busy_start - cursor
                if gap >= min_duration:
                    free_slots.append(TimeSlot(start=cursor, end=busy_start))
            cursor = max(cursor, busy_end)

        # Trailing gap after last event
        if cursor < day_end:
            gap = day_end - cursor
            if gap >= min_duration:
                free_slots.append(TimeSlot(start=cursor, end=day_end))

        return free_slots

    @staticmethod
    def _overlap_minutes(
        s1: datetime, e1: datetime, s2: datetime, e2: datetime
    ) -> int:
        """Calculate overlap in minutes between two intervals."""
        overlap_start = max(s1, s2)
        overlap_end = min(e1, e2)
        if overlap_start < overlap_end:
            return int((overlap_end - overlap_start).total_seconds() / 60)
        return 0

    def _fmt(self, dt: datetime) -> str:
        """Format datetime for Google Calendar API."""
        return self.calendar_manager._format_datetime_for_api(dt)

    def _parse_event_dt(self, event: dict, key: str) -> Optional[datetime]:
        """Parse start/end datetime from a Google Calendar event dict."""
        dt_info = event.get(key, {})
        dt_str = dt_info.get("dateTime") if isinstance(dt_info, dict) else None
        if not dt_str:
            # All-day event — skip for time-based conflict checks
            return None
        try:
            return self.calendar_manager._validate_datetime(dt_str)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _time_from_str(time_str: str) -> dt_time:
        """Parse 'HH:MM' into a time object."""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))


# ─── Gemini Tool Wrappers ──────────────────────────────────────────────────


class CheckConflictsTool(BaseTool):
    """
    Gemini tool: check if a proposed time window has scheduling conflicts.

    Returns conflicting events with overlap details, enabling the brain
    to warn the user and offer alternatives.
    """

    def _get_scheduler(self, session):
        if not session or not hasattr(session, "calendar_manager") or not session.calendar_manager:
            raise ValueError("Calendar manager not initialized.")
        return SchedulerService(session.calendar_manager)

    @property
    def name(self) -> str:
        return "check_calendar_conflicts"

    @property
    def description(self) -> str:
        return (
            "Check if a proposed time window conflicts with existing calendar events. "
            "Use this before creating or moving an event to detect scheduling conflicts. "
            "Returns a list of conflicting events with overlap details."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "ISO 8601 start time of the proposed window.",
                },
                "end_time": {
                    "type": "string",
                    "description": "ISO 8601 end time of the proposed window.",
                },
            },
            "required": ["start_time", "end_time"],
        }

    async def execute(self, session, **kwargs) -> Any:
        start_str = kwargs.get("start_time", "")
        end_str = kwargs.get("end_time", "")

        try:
            scheduler = self._get_scheduler(session)
            start = scheduler.calendar_manager._validate_datetime(start_str)
            end = scheduler.calendar_manager._validate_datetime(end_str)
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid datetime: {e}"}

        if not start or not end:
            return {"error": "Could not parse start_time or end_time."}

        conflicts = scheduler.check_conflicts(start, end)

        if conflicts:
            return {
                "has_conflicts": True,
                "count": len(conflicts),
                "conflicts": [c.to_dict() for c in conflicts],
            }
        else:
            return {
                "has_conflicts": False,
                "count": 0,
                "conflicts": [],
                "message": "No conflicts found — the time slot is free.",
            }


class FindFreeSlotsTool(BaseTool):
    """
    Gemini tool: find available time slots on a given date.

    Answers queries like "When am I free tomorrow?" or
    "Find me a 1-hour slot on Friday".
    """

    def _get_scheduler(self, session):
        if not session or not hasattr(session, "calendar_manager") or not session.calendar_manager:
            raise ValueError("Calendar manager not initialized.")
        return SchedulerService(session.calendar_manager)

    @property
    def name(self) -> str:
        return "find_free_slots"

    @property
    def description(self) -> str:
        return (
            "Find available time slots on a given date within working hours. "
            "Use this to answer 'When am I free?', 'Find me a 1-hour slot', etc. "
            "Returns a list of free time windows with their durations."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "ISO 8601 date or datetime for the target day (e.g. '2026-06-05').",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Minimum slot duration in minutes (default 30).",
                },
                "working_hours_start": {
                    "type": "string",
                    "description": "Start of working hours in HH:MM format (default '09:00').",
                },
                "working_hours_end": {
                    "type": "string",
                    "description": "End of working hours in HH:MM format (default '21:00').",
                },
            },
            "required": ["date"],
        }

    async def execute(self, session, **kwargs) -> Any:
        date_str = kwargs.get("date", "")
        duration = int(kwargs.get("duration_minutes", 30))
        wh_start = kwargs.get("working_hours_start", "09:00")
        wh_end = kwargs.get("working_hours_end", "21:00")

        try:
            scheduler = self._get_scheduler(session)
            target_date = scheduler.calendar_manager._validate_datetime(date_str)
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid date: {e}"}

        if not target_date:
            return {"error": "Could not parse the date."}

        free = scheduler.find_free_slots(
            target_date, duration, (wh_start, wh_end)
        )

        if free:
            return {
                "date": target_date.strftime("%Y-%m-%d"),
                "duration_requested": duration,
                "slots_found": len(free),
                "free_slots": [s.to_dict() for s in free],
            }
        else:
            return {
                "date": target_date.strftime("%Y-%m-%d"),
                "duration_requested": duration,
                "slots_found": 0,
                "free_slots": [],
                "message": f"No free slots of {duration}+ minutes found on {target_date.strftime('%B %d')}.",
            }


class SuggestAlternativesTool(BaseTool):
    """
    Gemini tool: suggest alternative time slots near a conflicting time.

    When a conflict is detected, this tool finds the nearest available
    slots and ranks them by proximity to the originally requested time.
    """

    def _get_scheduler(self, session):
        if not session or not hasattr(session, "calendar_manager") or not session.calendar_manager:
            raise ValueError("Calendar manager not initialized.")
        return SchedulerService(session.calendar_manager)

    @property
    def name(self) -> str:
        return "suggest_alternative_slots"

    @property
    def description(self) -> str:
        return (
            "Suggest alternative available time slots near a conflicting time. "
            "Use this after detecting a conflict to offer the user ranked alternatives. "
            "Returns slots scored by proximity to the original requested time."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "conflicting_start": {
                    "type": "string",
                    "description": "ISO 8601 start time of the conflicting slot.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "description": "Required event duration in minutes.",
                },
                "max_suggestions": {
                    "type": "integer",
                    "description": "Maximum number of alternatives to return (default 3).",
                },
            },
            "required": ["conflicting_start", "duration_minutes"],
        }

    async def execute(self, session, **kwargs) -> Any:
        start_str = kwargs.get("conflicting_start", "")
        duration = int(kwargs.get("duration_minutes", 30))
        max_sugg = int(kwargs.get("max_suggestions", 3))

        try:
            scheduler = self._get_scheduler(session)
            start = scheduler.calendar_manager._validate_datetime(start_str)
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid datetime: {e}"}

        if not start:
            return {"error": "Could not parse conflicting_start."}

        alternatives = scheduler.suggest_alternatives(
            start, duration, max_sugg
        )

        if alternatives:
            return {
                "original_time": start.isoformat(),
                "alternatives_found": len(alternatives),
                "alternatives": [s.to_dict() for s in alternatives],
            }
        else:
            return {
                "original_time": start.isoformat(),
                "alternatives_found": 0,
                "alternatives": [],
                "message": "No alternative slots found in the next 3 days.",
            }
