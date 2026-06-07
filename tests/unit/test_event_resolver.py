"""
Tests for EventResolver — Phase 4: Semantic Event Resolution

Covers 15+ scenarios across all 5 resolution strategies:
- Pronoun resolution
- Exact title matching
- Fuzzy title matching
- Temporal reference resolution
- Contextual reference resolution
- Edge cases and disambiguation
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass, field
from typing import Any, Optional, List

from ava.conversation.event_resolver import EventResolver, ResolvedEvent
from ava.conversation.state_manager import ConversationState


# ─── Fixtures ───────────────────────────────────────────────────────────────


def make_event(
    event_id: str = "evt_1",
    title: str = "Test Event",
    start_hour: int = 10,
    end_hour: int = 11,
    date: str = "2026-06-05",
) -> dict:
    """Create a mock Google Calendar event dict."""
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": f"{date}T{start_hour:02d}:00:00+05:30"},
        "end": {"dateTime": f"{date}T{end_hour:02d}:00:00+05:30"},
    }


SAMPLE_EVENTS = [
    make_event("evt_1", "Project Discussion", 14, 15),
    make_event("evt_2", "Internship Meeting", 10, 11),
    make_event("evt_3", "Team Standup", 9, 9),
    make_event("evt_4", "Lunch with Rahul", 12, 13),
    make_event("evt_5", "Code Review Session", 16, 17),
]


def make_mock_calendar_manager(events: list = None):
    """Create a mock CalendarManager that returns predefined events."""
    if events is None:
        events = SAMPLE_EVENTS

    mock_service = MagicMock()
    mock_events_list = MagicMock()
    mock_events_list.execute.return_value = {"items": events}
    mock_service.events.return_value.list.return_value = mock_events_list

    manager = MagicMock()
    manager._get_calendar_service.return_value = mock_service
    return manager


def make_state(
    last_event: dict = None,
    mentioned_events: list = None,
    history: list = None,
) -> ConversationState:
    """Create a ConversationState with optional pre-filled data."""
    state = ConversationState(session_id="test_session")
    if last_event:
        state.last_event = last_event
    if mentioned_events:
        state.last_mentioned_events = mentioned_events
    if history:
        state.conversation_history = history
    return state


# ─── 1. Pronoun Resolution ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pronoun_it_resolves_last_event():
    """'delete it' should resolve to the last mentioned event."""
    last = make_event("evt_99", "Important Meeting", 14, 15)
    state = make_state(last_event=last)
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("it", state)

    assert result is not None
    assert result.event_id == "evt_99"
    assert result.title == "Important Meeting"
    assert result.strategy == "pronoun"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_pronoun_that_one_resolves():
    """'that one' should resolve via pronoun strategy."""
    last = make_event("evt_42", "Design Review", 11, 12)
    state = make_state(last_event=last)
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("that one", state)

    assert result is not None
    assert result.event_id == "evt_42"
    assert result.strategy == "pronoun"


@pytest.mark.asyncio
async def test_pronoun_the_meeting_resolves():
    """'the meeting' should resolve via pronoun strategy."""
    last = make_event("evt_7", "Sprint Planning", 10, 11)
    state = make_state(last_event=last)
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("the meeting", state)

    assert result is not None
    assert result.event_id == "evt_7"
    assert result.strategy == "pronoun"


@pytest.mark.asyncio
async def test_pronoun_no_last_event_returns_none():
    """Pronoun with no last_event in state should return None (fallthrough)."""
    state = make_state(last_event=None)
    # Also no events in calendar to match against
    resolver = EventResolver(make_mock_calendar_manager(events=[]))

    result = await resolver.resolve("it", state)

    assert result is None


# ─── 2. Exact Title Match ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_title_match():
    """Exact title 'Project Discussion' should match with confidence 1.0."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("Project Discussion", state)

    assert result is not None
    assert result.event_id == "evt_1"
    assert result.title == "Project Discussion"
    assert result.strategy == "exact_title"
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_exact_title_case_insensitive():
    """Title matching should be case-insensitive."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("project discussion", state)

    assert result is not None
    assert result.event_id == "evt_1"
    assert result.strategy == "exact_title"


@pytest.mark.asyncio
async def test_exact_title_internship_meeting():
    """Direct title match for 'Internship Meeting'."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("Internship Meeting", state)

    assert result is not None
    assert result.event_id == "evt_2"
    assert result.strategy == "exact_title"


# ─── 3. Fuzzy Title Match ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fuzzy_match_partial_title():
    """'project meet' should fuzzy-match 'Project Discussion' or similar."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("Project Discuss", state)

    assert result is not None
    assert result.event_id == "evt_1"
    # Could be substring or fuzzy depending on ratio
    assert result.strategy in ("substring_title", "fuzzy_title")
    assert result.confidence >= 0.6


@pytest.mark.asyncio
async def test_fuzzy_match_substring():
    """'Code Review' should match 'Code Review Session' via substring."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("Code Review", state)

    assert result is not None
    assert result.event_id == "evt_5"
    assert result.strategy == "substring_title"


@pytest.mark.asyncio
async def test_fuzzy_match_below_threshold_returns_none():
    """A completely unrelated string should not match any event."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("Quantum Physics Lecture", state)

    assert result is None


@pytest.mark.asyncio
async def test_fuzzy_match_team_standup():
    """'team stand up' should fuzzy-match 'Team Standup'."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("team stand up", state)

    assert result is not None
    assert result.event_id == "evt_3"
    assert result.confidence >= 0.6


# ─── 4. Temporal Reference ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_temporal_today_single_event():
    """'today's meeting' with one event today should resolve it."""
    single_event = [make_event("evt_today", "Morning Sync", 9, 10)]
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager(events=single_event))

    with patch("ava.conversation.event_resolver.datetime") as mock_dt:
        mock_now = datetime(2026, 6, 5, 8, 0, 0)
        mock_dt.now.return_value = mock_now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        result = await resolver.resolve("today's meeting", state)

    assert result is not None
    assert result.strategy == "temporal"


@pytest.mark.asyncio
async def test_temporal_tomorrow_meeting():
    """'tomorrow's meeting' should attempt temporal resolution."""
    events = [make_event("evt_tmr", "Planning Session", 10, 11, "2026-06-06")]
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager(events=events))

    result = await resolver.resolve("tomorrow's meeting", state)

    # Should resolve via temporal strategy
    assert result is not None
    assert result.strategy == "temporal"


# ─── 5. Contextual Reference ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contextual_the_one_we_discussed():
    """'the one we discussed' should resolve via contextual strategy."""
    mentioned = [make_event("evt_ctx", "Budget Review", 15, 16)]
    state = make_state(mentioned_events=mentioned)
    resolver = EventResolver(make_mock_calendar_manager(events=[]))

    result = await resolver.resolve("the one we discussed", state)

    assert result is not None
    assert result.event_id == "evt_ctx"
    assert result.title == "Budget Review"
    assert result.strategy == "contextual"


@pytest.mark.asyncio
async def test_contextual_falls_back_to_last_event():
    """Contextual reference without mentioned_events falls back to last_event."""
    last = make_event("evt_last", "Standup", 9, 10)
    state = make_state(last_event=last, mentioned_events=[])
    resolver = EventResolver(make_mock_calendar_manager(events=[]))

    result = await resolver.resolve("the one we talked about", state)

    assert result is not None
    assert result.event_id == "evt_last"
    assert result.strategy == "contextual"


@pytest.mark.asyncio
async def test_contextual_no_history_returns_none():
    """Contextual reference with no history/events should return None."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager(events=[]))

    result = await resolver.resolve("the one we discussed", state)

    assert result is None


# ─── 6. Edge Cases & Disambiguation ────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_reference_returns_none():
    """Empty string should return None."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    result = await resolver.resolve("", state)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_all_returns_multiple_ranked():
    """resolve_all should return multiple matches ranked by confidence."""
    state = make_state()
    resolver = EventResolver(make_mock_calendar_manager())

    results = await resolver.resolve_all("meeting", state)

    # Should find at least "Internship Meeting" via substring
    assert len(results) >= 1
    # Results should be sorted by confidence descending
    for i in range(len(results) - 1):
        assert results[i].confidence >= results[i + 1].confidence


@pytest.mark.asyncio
async def test_no_calendar_service_returns_none():
    """If calendar service is unavailable, resolve should return None gracefully."""
    manager = MagicMock()
    manager._get_calendar_service.return_value = None
    state = make_state()
    resolver = EventResolver(manager)

    result = await resolver.resolve("Project Discussion", state)

    assert result is None


# ─── 7. ResolvedEvent Model ────────────────────────────────────────────────


def test_resolved_event_to_dict():
    """ResolvedEvent.to_dict() should return all fields."""
    event = ResolvedEvent(
        event_id="e1",
        title="Test",
        start="2026-06-05T10:00:00",
        end="2026-06-05T11:00:00",
        strategy="exact_title",
        confidence=1.0,
    )
    d = event.to_dict()
    assert d["event_id"] == "e1"
    assert d["title"] == "Test"
    assert d["strategy"] == "exact_title"
    assert d["confidence"] == 1.0


def test_resolved_event_repr():
    """ResolvedEvent.__repr__ should be readable."""
    event = ResolvedEvent(
        event_id="e1", title="Test", strategy="fuzzy_title", confidence=0.85
    )
    assert "Test" in repr(event)
    assert "fuzzy_title" in repr(event)


# ─── 8. ConversationState Enhancements ─────────────────────────────────────


def test_track_event_updates_last_event():
    """track_event should set last_event and append to last_mentioned_events."""
    state = ConversationState(session_id="s1")
    event = make_event("e1", "Meeting A")

    state.track_event(event)

    assert state.last_event == event
    assert len(state.last_mentioned_events) == 1
    assert state.last_mentioned_events[0] == event


def test_track_event_respects_max():
    """track_event should trim to MAX_MENTIONED_EVENTS."""
    state = ConversationState(session_id="s1")
    state.MAX_MENTIONED_EVENTS = 3

    for i in range(5):
        state.track_event(make_event(f"e{i}", f"Event {i}"))

    assert len(state.last_mentioned_events) == 3
    # Should keep the last 3
    assert state.last_mentioned_events[0]["id"] == "e2"
    assert state.last_mentioned_events[2]["id"] == "e4"


def test_add_turn_stores_history():
    """add_turn should append to conversation_history."""
    state = ConversationState(session_id="s1")

    state.add_turn("user", "Schedule a meeting tomorrow")
    state.add_turn("assistant", "What time should I schedule it?")

    assert len(state.conversation_history) == 2
    assert state.conversation_history[0]["role"] == "user"
    assert state.conversation_history[1]["role"] == "assistant"


def test_add_turn_respects_max():
    """add_turn should trim to MAX_HISTORY_TURNS."""
    state = ConversationState(session_id="s1")
    state.MAX_HISTORY_TURNS = 3

    for i in range(5):
        state.add_turn("user", f"Turn {i}")

    assert len(state.conversation_history) == 3
    assert state.conversation_history[0]["content"] == "Turn 2"


def test_track_event_ignores_none():
    """track_event(None) should be a no-op."""
    state = ConversationState(session_id="s1")
    state.track_event(None)
    assert state.last_event is None
    assert len(state.last_mentioned_events) == 0
