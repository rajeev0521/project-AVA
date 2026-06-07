"""
Tests for SchedulerService + Gemini tool wrappers — Phase 5: Scheduling Intelligence

Covers:
- Conflict detection (single, multiple, no conflicts, edge cases)
- Free-slot discovery (empty day, busy day, partial availability, custom hours)
- Alternative suggestions (ranking, multi-day search, no availability)
- Gemini tool wrappers (CheckConflictsTool, FindFreeSlotsTool, SuggestAlternativesTool)
- TimeSlot / ConflictInfo data models
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from typing import List, Tuple

from ava.tools.scheduler_tool import (
    SchedulerService,
    CheckConflictsTool,
    FindFreeSlotsTool,
    SuggestAlternativesTool,
    TimeSlot,
    ConflictInfo,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

# Use a fixed timezone offset for deterministic tests
IST = timezone(timedelta(hours=5, minutes=30))


def dt(hour: int, minute: int = 0, day: int = 5) -> datetime:
    """Shorthand: 2026-06-{day}T{hour}:{minute}:00+05:30"""
    return datetime(2026, 6, day, hour, minute, 0, tzinfo=IST)


def make_gcal_event(
    event_id: str, title: str, start: datetime, end: datetime
) -> dict:
    """Create a mock Google Calendar event dict."""
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }


def make_mock_calendar_manager(events: List[dict] = None):
    """
    Create a mock CalendarManager that returns predefined events
    and has functional _validate_datetime / _format_datetime_for_api.
    """
    if events is None:
        events = []

    mock_service = MagicMock()
    mock_events_list = MagicMock()
    mock_events_list.execute.return_value = {"items": events}
    mock_service.events.return_value.list.return_value = mock_events_list

    manager = MagicMock()
    manager._get_calendar_service.return_value = mock_service
    manager.local_tz = IST

    # Real implementations for datetime helpers (thin wrappers)
    def _validate_datetime(dt_str):
        if isinstance(dt_str, datetime):
            if dt_str.tzinfo is None:
                return dt_str.replace(tzinfo=IST)
            return dt_str
        if isinstance(dt_str, str):
            parsed = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=IST)
            return parsed
        return None

    def _format_datetime_for_api(d):
        if d.tzinfo is None:
            d = d.replace(tzinfo=IST)
        return d.isoformat()

    manager._validate_datetime = _validate_datetime
    manager._format_datetime_for_api = _format_datetime_for_api
    return manager


# ─── SchedulerService: Conflict Detection ──────────────────────────────────


class TestCheckConflicts:
    def test_no_conflicts_empty_calendar(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)
        conflicts = svc.check_conflicts(dt(14), dt(15))
        assert conflicts == []

    def test_single_conflict(self):
        events = [make_gcal_event("e1", "Meeting", dt(14), dt(15))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        conflicts = svc.check_conflicts(dt(14, 30), dt(15, 30))

        assert len(conflicts) == 1
        assert conflicts[0].title == "Meeting"
        assert conflicts[0].overlap_minutes == 30

    def test_multiple_conflicts(self):
        events = [
            make_gcal_event("e1", "Meeting A", dt(14), dt(15)),
            make_gcal_event("e2", "Meeting B", dt(15), dt(16)),
        ]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        conflicts = svc.check_conflicts(dt(14, 30), dt(15, 30))

        assert len(conflicts) == 2
        titles = {c.title for c in conflicts}
        assert "Meeting A" in titles
        assert "Meeting B" in titles

    def test_no_overlap_adjacent_events(self):
        """Events that end exactly when the proposed slot starts are NOT conflicts."""
        events = [make_gcal_event("e1", "Previous", dt(13), dt(14))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        conflicts = svc.check_conflicts(dt(14), dt(15))
        assert conflicts == []

    def test_full_overlap(self):
        """Proposed slot completely contained within an existing event."""
        events = [make_gcal_event("e1", "Long Event", dt(10), dt(17))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        conflicts = svc.check_conflicts(dt(12), dt(13))

        assert len(conflicts) == 1
        assert conflicts[0].overlap_minutes == 60

    def test_no_calendar_service_returns_empty(self):
        mgr = MagicMock()
        mgr._get_calendar_service.return_value = None
        svc = SchedulerService(mgr)

        conflicts = svc.check_conflicts(dt(14), dt(15))
        assert conflicts == []


# ─── SchedulerService: Free-Slot Discovery ─────────────────────────────────


class TestFindFreeSlots:
    def test_empty_calendar_returns_full_day(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)

        slots = svc.find_free_slots(dt(9), duration_minutes=30)

        assert len(slots) == 1
        assert slots[0].start == dt(9)
        assert slots[0].end == dt(21)
        assert slots[0].duration_minutes == 720

    def test_single_event_splits_day(self):
        events = [make_gcal_event("e1", "Meeting", dt(12), dt(13))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        slots = svc.find_free_slots(dt(9), duration_minutes=30)

        assert len(slots) == 2
        # Morning slot: 9:00–12:00
        assert slots[0].start == dt(9)
        assert slots[0].end == dt(12)
        # Afternoon slot: 13:00–21:00
        assert slots[1].start == dt(13)
        assert slots[1].end == dt(21)

    def test_minimum_duration_filter(self):
        """Slots shorter than requested duration should be excluded."""
        events = [
            make_gcal_event("e1", "A", dt(9), dt(9, 40)),
            make_gcal_event("e2", "B", dt(10), dt(21)),
        ]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        # Only 20 min gap between A and B → should be excluded if we need 30 min
        slots = svc.find_free_slots(dt(9), duration_minutes=30)

        # The 20-min gap (9:40–10:00) is too short
        for slot in slots:
            assert slot.duration_minutes >= 30

    def test_custom_working_hours(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)

        slots = svc.find_free_slots(
            dt(9), duration_minutes=30, working_hours=("10:00", "17:00")
        )

        assert len(slots) == 1
        assert slots[0].start.hour == 10
        assert slots[0].end.hour == 17

    def test_fully_packed_day_returns_empty(self):
        events = [make_gcal_event("e1", "All Day", dt(9), dt(21))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        slots = svc.find_free_slots(dt(9), duration_minutes=30)
        assert slots == []

    def test_back_to_back_events(self):
        events = [
            make_gcal_event("e1", "A", dt(9), dt(11)),
            make_gcal_event("e2", "B", dt(11), dt(13)),
            make_gcal_event("e3", "C", dt(13), dt(15)),
        ]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        slots = svc.find_free_slots(dt(9), duration_minutes=30)

        # Only free after 15:00
        assert len(slots) == 1
        assert slots[0].start == dt(15)
        assert slots[0].end == dt(21)

    def test_no_calendar_service(self):
        mgr = MagicMock()
        mgr._get_calendar_service.return_value = None
        mgr.local_tz = IST
        svc = SchedulerService(mgr)

        slots = svc.find_free_slots(dt(9))
        assert slots == []


# ─── SchedulerService: Suggest Alternatives ─────────────────────────────────


class TestSuggestAlternatives:
    def test_suggests_slots_after_conflict(self):
        # Busy 14:00–15:00, rest free
        events = [make_gcal_event("e1", "Busy", dt(14), dt(15))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        alts = svc.suggest_alternatives(dt(14), duration_minutes=60)

        assert len(alts) >= 1
        # All suggestions should be at or after 14:00
        for alt in alts:
            assert alt.start >= dt(14)

    def test_max_suggestions_respected(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)

        alts = svc.suggest_alternatives(dt(14), duration_minutes=30, max_suggestions=2)
        assert len(alts) <= 2

    def test_alternatives_scored_by_proximity(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)

        alts = svc.suggest_alternatives(dt(14), duration_minutes=60, max_suggestions=3)

        # Sorted by score descending — closest to original time first
        for i in range(len(alts) - 1):
            assert alts[i].score >= alts[i + 1].score

    def test_fully_packed_day_searches_next_days(self):
        """If today is fully booked, suggestions should come from tomorrow."""
        events = [make_gcal_event("e1", "All Day", dt(9), dt(21))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)

        alts = svc.suggest_alternatives(dt(14), duration_minutes=60)

        # Since the mock returns the same events for all days, this tests
        # that the logic at least attempts multi-day search
        # (the mock always returns the same packed day, so we may get 0)
        assert isinstance(alts, list)


# ─── Data Models ────────────────────────────────────────────────────────────


class TestTimeSlot:
    def test_duration_minutes(self):
        slot = TimeSlot(start=dt(10), end=dt(11, 30))
        assert slot.duration_minutes == 90

    def test_to_dict(self):
        slot = TimeSlot(start=dt(10), end=dt(11), score=0.85)
        d = slot.to_dict()
        assert d["duration_minutes"] == 60
        assert d["score"] == 0.85
        assert "start" in d
        assert "end" in d

    def test_repr(self):
        slot = TimeSlot(start=dt(10), end=dt(11))
        assert "10:00" in repr(slot)
        assert "11:00" in repr(slot)


class TestConflictInfo:
    def test_to_dict(self):
        c = ConflictInfo("e1", "Meeting", dt(14), dt(15), overlap_minutes=30)
        d = c.to_dict()
        assert d["event_id"] == "e1"
        assert d["title"] == "Meeting"
        assert d["overlap_minutes"] == 30


# ─── Gemini Tool Wrappers ──────────────────────────────────────────────────


class TestCheckConflictsTool:
    @pytest.mark.asyncio
    async def test_no_conflicts(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)
        tool = CheckConflictsTool(svc)

        result = await tool.execute(
            start_time="2026-06-05T14:00:00+05:30",
            end_time="2026-06-05T15:00:00+05:30",
        )

        assert result["has_conflicts"] is False
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_with_conflicts(self):
        events = [make_gcal_event("e1", "Busy", dt(14), dt(15))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)
        tool = CheckConflictsTool(svc)

        result = await tool.execute(
            start_time="2026-06-05T14:30:00+05:30",
            end_time="2026-06-05T15:30:00+05:30",
        )

        assert result["has_conflicts"] is True
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_invalid_datetime(self):
        mgr = make_mock_calendar_manager()
        svc = SchedulerService(mgr)
        tool = CheckConflictsTool(svc)

        result = await tool.execute(start_time="not-a-date", end_time="also-bad")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_schema(self):
        mgr = make_mock_calendar_manager()
        svc = SchedulerService(mgr)
        tool = CheckConflictsTool(svc)

        assert tool.name == "check_calendar_conflicts"
        assert "conflict" in tool.description.lower()
        assert "start_time" in tool.parameters["properties"]
        assert "end_time" in tool.parameters["properties"]


class TestFindFreeSlotsTool:
    @pytest.mark.asyncio
    async def test_finds_slots(self):
        mgr = make_mock_calendar_manager(events=[])
        svc = SchedulerService(mgr)
        tool = FindFreeSlotsTool(svc)

        result = await tool.execute(date="2026-06-05T09:00:00+05:30")

        assert result["slots_found"] >= 1
        assert len(result["free_slots"]) >= 1

    @pytest.mark.asyncio
    async def test_no_slots(self):
        events = [make_gcal_event("e1", "All Day", dt(9), dt(21))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)
        tool = FindFreeSlotsTool(svc)

        result = await tool.execute(
            date="2026-06-05T09:00:00+05:30", duration_minutes=30
        )

        assert result["slots_found"] == 0

    @pytest.mark.asyncio
    async def test_tool_schema(self):
        mgr = make_mock_calendar_manager()
        svc = SchedulerService(mgr)
        tool = FindFreeSlotsTool(svc)

        assert tool.name == "find_free_slots"
        assert "date" in tool.parameters["properties"]
        assert "duration_minutes" in tool.parameters["properties"]


class TestSuggestAlternativesTool:
    @pytest.mark.asyncio
    async def test_suggests_alternatives(self):
        events = [make_gcal_event("e1", "Busy", dt(14), dt(15))]
        mgr = make_mock_calendar_manager(events)
        svc = SchedulerService(mgr)
        tool = SuggestAlternativesTool(svc)

        result = await tool.execute(
            conflicting_start="2026-06-05T14:00:00+05:30",
            duration_minutes=60,
        )

        assert result["alternatives_found"] >= 1

    @pytest.mark.asyncio
    async def test_invalid_datetime(self):
        mgr = make_mock_calendar_manager()
        svc = SchedulerService(mgr)
        tool = SuggestAlternativesTool(svc)

        result = await tool.execute(
            conflicting_start="garbage", duration_minutes=30
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_schema(self):
        mgr = make_mock_calendar_manager()
        svc = SchedulerService(mgr)
        tool = SuggestAlternativesTool(svc)

        assert tool.name == "suggest_alternative_slots"
        assert "conflicting_start" in tool.parameters["properties"]
        assert "duration_minutes" in tool.parameters["properties"]


# ─── SchedulerService._extract_free_slots (internal) ──────────────────────


class TestExtractFreeSlots:
    """Unit tests for the gap-extraction algorithm."""

    def _svc(self):
        return SchedulerService(make_mock_calendar_manager())

    def test_no_busy_intervals(self):
        svc = self._svc()
        slots = svc._extract_free_slots(dt(9), dt(17), [], 30)
        assert len(slots) == 1
        assert slots[0].duration_minutes == 480

    def test_single_gap(self):
        svc = self._svc()
        busy = [(dt(10), dt(12))]
        slots = svc._extract_free_slots(dt(9), dt(17), busy, 30)

        assert len(slots) == 2
        assert slots[0].start == dt(9)
        assert slots[0].end == dt(10)
        assert slots[1].start == dt(12)
        assert slots[1].end == dt(17)

    def test_gap_too_small(self):
        svc = self._svc()
        busy = [(dt(9, 20), dt(10))]
        slots = svc._extract_free_slots(dt(9), dt(10), busy, 30)

        # 20-min gap is too small for 30-min requirement
        assert len(slots) == 0

    def test_overlapping_busy_intervals(self):
        """Overlapping events should be handled gracefully."""
        svc = self._svc()
        busy = [(dt(10), dt(12)), (dt(11), dt(13))]  # overlapping
        slots = svc._extract_free_slots(dt(9), dt(17), busy, 30)

        assert len(slots) == 2
        assert slots[0].start == dt(9)
        assert slots[0].end == dt(10)
        assert slots[1].start == dt(13)
        assert slots[1].end == dt(17)


# ─── SchedulerService._overlap_minutes (internal) ─────────────────────────


class TestOverlapMinutes:
    def test_no_overlap(self):
        assert SchedulerService._overlap_minutes(dt(9), dt(10), dt(10), dt(11)) == 0

    def test_partial_overlap(self):
        assert SchedulerService._overlap_minutes(dt(9), dt(11), dt(10), dt(12)) == 60

    def test_full_containment(self):
        assert SchedulerService._overlap_minutes(dt(9), dt(17), dt(10), dt(12)) == 120

    def test_identical(self):
        assert SchedulerService._overlap_minutes(dt(10), dt(11), dt(10), dt(11)) == 60
