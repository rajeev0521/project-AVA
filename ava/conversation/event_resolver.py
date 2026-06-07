"""
Semantic Event Resolver for AVA 2.0

Resolves vague event references (pronouns, fuzzy titles, temporal hints)
to concrete Google Calendar event IDs.

Resolution strategies (in priority order):
1. Pronoun resolution     — "it", "that one", "the meeting"
2. Exact title match      — "Project Discussion"
3. Fuzzy title match      — "project meet", "intern mtg"
4. Temporal reference     — "tomorrow's meeting", "today's 4pm event"
5. Contextual reference   — "the one we discussed" (conversation history)
"""

import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ava.logger import get_logger

logger = get_logger(__name__)

# Patterns that indicate the user is referring to a previously-mentioned event
PRONOUN_PATTERNS = [
    r"^\s*it\s*$",
    r"\bthat\s+one\b",
    r"\bthat\s+event\b",
    r"\bthe\s+event\b",
    r"\bthe\s+meeting\b",
    r"\bthis\s+one\b",
    r"\bthis\s+event\b",
    r"\bthis\s+meeting\b",
    r"\bsame\s+one\b",
    r"\bsame\s+event\b",
    r"\bsame\s+meeting\b",
    r"\bprevious\s+one\b",
    r"\blast\s+one\b",
    r"\blast\s+event\b",
    r"\blast\s+meeting\b",
]

# Patterns suggesting a temporal reference (used to detect strategy)
TEMPORAL_PATTERNS = [
    r"\btoday'?s?\b",
    r"\btomorrow'?s?\b",
    r"\byesterday'?s?\b",
    r"\btonight'?s?\b",
    r"\bthis\s+(morning|afternoon|evening|week)\b",
    r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
]

# Contextual reference patterns
CONTEXTUAL_PATTERNS = [
    r"\bthe\s+one\s+we\s+(discussed|talked\s+about|mentioned)\b",
    r"\bwhat\s+we\s+(discussed|talked\s+about|mentioned)\b",
    r"\bthat\s+thing\s+we\b",
    r"\bthe\s+one\s+I\s+(mentioned|said|told)\b",
    r"\bthe\s+one\s+from\s+(earlier|before)\b",
]


class ResolvedEvent:
    """Represents a resolved calendar event with a confidence score."""

    def __init__(
        self,
        event_id: str,
        title: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        strategy: str = "unknown",
        confidence: float = 0.0,
        raw_event: Optional[Dict[str, Any]] = None,
    ):
        self.event_id = event_id
        self.title = title
        self.start = start
        self.end = end
        self.strategy = strategy
        self.confidence = confidence
        self.raw_event = raw_event or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "strategy": self.strategy,
            "confidence": self.confidence,
        }

    def __repr__(self) -> str:
        return (
            f"ResolvedEvent(title='{self.title}', strategy='{self.strategy}', "
            f"confidence={self.confidence:.2f})"
        )


class EventResolver:
    """
    Resolves vague event references to concrete Google Calendar events.

    Uses a cascade of resolution strategies to find the best match.
    """

    def __init__(
        self,
        calendar_manager: Any,
        fuzzy_threshold: float = 0.6,
    ):
        """
        Args:
            calendar_manager: CalendarManager instance for querying events.
            fuzzy_threshold: Minimum SequenceMatcher ratio for fuzzy matches.
        """
        self.calendar_manager = calendar_manager
        self.fuzzy_threshold = fuzzy_threshold

    async def resolve(
        self,
        reference: str,
        conversation_state: Any,
        date_hint: Optional[str] = None,
    ) -> Optional[ResolvedEvent]:
        """
        Resolve an ambiguous event reference to a concrete calendar event.

        Tries strategies in priority order and returns the first confident match.

        Args:
            reference: The user's event reference (e.g., "it", "project meet").
            conversation_state: The current ConversationState for context.
            date_hint: Optional ISO date string to narrow the search window.

        Returns:
            A ResolvedEvent if found, else None.
        """
        reference_clean = reference.strip()
        if not reference_clean:
            return None

        logger.info(f"Resolving event reference: '{reference_clean}'")

        # Strategy 1: Pronoun resolution
        result = self._resolve_pronoun(reference_clean, conversation_state)
        if result:
            logger.info(f"Resolved via pronoun: {result}")
            return result

        # Strategy 2 & 3: Exact + fuzzy title matching
        result = await self._resolve_by_title(reference_clean, date_hint)
        if result:
            logger.info(f"Resolved via title matching: {result}")
            return result

        # Strategy 4: Temporal reference
        result = await self._resolve_temporal(reference_clean, conversation_state)
        if result:
            logger.info(f"Resolved via temporal reference: {result}")
            return result

        # Strategy 5: Contextual reference from conversation history
        result = self._resolve_contextual(reference_clean, conversation_state)
        if result:
            logger.info(f"Resolved via contextual reference: {result}")
            return result

        logger.warning(f"Could not resolve event reference: '{reference_clean}'")
        return None

    async def resolve_all(
        self,
        reference: str,
        conversation_state: Any,
        date_hint: Optional[str] = None,
        max_results: int = 5,
    ) -> List[ResolvedEvent]:
        """
        Find all possible matches for an event reference, ranked by confidence.

        Useful for disambiguation when multiple events match.
        """
        reference_clean = reference.strip()
        if not reference_clean:
            return []

        results: List[ResolvedEvent] = []

        # Check pronoun first
        pronoun_result = self._resolve_pronoun(reference_clean, conversation_state)
        if pronoun_result:
            results.append(pronoun_result)

        # Find by title (both exact and fuzzy)
        title_results = await self._find_by_title(reference_clean, date_hint)
        results.extend(title_results)

        # Contextual
        ctx_result = self._resolve_contextual(reference_clean, conversation_state)
        if ctx_result:
            results.append(ctx_result)

        # Deduplicate by event_id, keeping highest confidence
        seen: Dict[str, ResolvedEvent] = {}
        for r in results:
            if r.event_id not in seen or r.confidence > seen[r.event_id].confidence:
                seen[r.event_id] = r

        ranked = sorted(seen.values(), key=lambda x: x.confidence, reverse=True)
        return ranked[:max_results]

    # ──────────────────────────────────────────────
    # Strategy 1: Pronoun Resolution
    # ──────────────────────────────────────────────

    def _resolve_pronoun(
        self, reference: str, conversation_state: Any
    ) -> Optional[ResolvedEvent]:
        """Resolve pronoun references ('it', 'that one', 'the meeting') via state."""
        ref_lower = reference.lower()

        is_pronoun = any(
            re.search(pattern, ref_lower) for pattern in PRONOUN_PATTERNS
        )

        if not is_pronoun:
            return None

        # Try last_event from conversation state
        last_event = getattr(conversation_state, "last_event", None)
        if not last_event:
            logger.debug("Pronoun detected but no last_event in state")
            return None

        # last_event can be a dict (from calendar API) or an object
        if isinstance(last_event, dict):
            return ResolvedEvent(
                event_id=last_event.get("id", ""),
                title=last_event.get("summary", last_event.get("title", "Unknown")),
                start=self._extract_start(last_event),
                end=self._extract_end(last_event),
                strategy="pronoun",
                confidence=1.0,
                raw_event=last_event,
            )
        else:
            # Object with attributes
            return ResolvedEvent(
                event_id=getattr(last_event, "id", getattr(last_event, "event_id", "")),
                title=getattr(last_event, "summary", getattr(last_event, "title", "Unknown")),
                start=getattr(last_event, "start", None),
                end=getattr(last_event, "end", None),
                strategy="pronoun",
                confidence=1.0,
                raw_event=last_event if isinstance(last_event, dict) else {},
            )

    # ──────────────────────────────────────────────
    # Strategy 2 & 3: Exact + Fuzzy Title Matching
    # ──────────────────────────────────────────────

    async def _resolve_by_title(
        self, reference: str, date_hint: Optional[str] = None
    ) -> Optional[ResolvedEvent]:
        """Resolve by exact or fuzzy title match."""
        matches = await self._find_by_title(reference, date_hint)
        if matches:
            return matches[0]  # Best match
        return None

    async def _find_by_title(
        self, reference: str, date_hint: Optional[str] = None
    ) -> List[ResolvedEvent]:
        """Find events matching the reference by title (exact + fuzzy)."""
        events = self._fetch_upcoming_events(date_hint)
        if not events:
            return []

        results: List[ResolvedEvent] = []
        ref_lower = reference.lower().strip()

        for event in events:
            event_title = event.get("summary", "")
            if not event_title:
                continue

            title_lower = event_title.lower().strip()

            # Exact match
            if ref_lower == title_lower:
                results.append(
                    ResolvedEvent(
                        event_id=event.get("id", ""),
                        title=event_title,
                        start=self._extract_start(event),
                        end=self._extract_end(event),
                        strategy="exact_title",
                        confidence=1.0,
                        raw_event=event,
                    )
                )
                continue

            # Substring match (reference is contained in title or vice versa)
            if ref_lower in title_lower or title_lower in ref_lower:
                # Score based on how much of the title is covered
                overlap = min(len(ref_lower), len(title_lower)) / max(
                    len(ref_lower), len(title_lower)
                )
                confidence = 0.7 + (0.25 * overlap)  # 0.7 – 0.95
                results.append(
                    ResolvedEvent(
                        event_id=event.get("id", ""),
                        title=event_title,
                        start=self._extract_start(event),
                        end=self._extract_end(event),
                        strategy="substring_title",
                        confidence=confidence,
                        raw_event=event,
                    )
                )
                continue

            # Fuzzy match
            ratio = SequenceMatcher(None, ref_lower, title_lower).ratio()
            if ratio >= self.fuzzy_threshold:
                results.append(
                    ResolvedEvent(
                        event_id=event.get("id", ""),
                        title=event_title,
                        start=self._extract_start(event),
                        end=self._extract_end(event),
                        strategy="fuzzy_title",
                        confidence=ratio,
                        raw_event=event,
                    )
                )

        # Sort by confidence descending
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    # ──────────────────────────────────────────────
    # Strategy 4: Temporal Reference Resolution
    # ──────────────────────────────────────────────

    async def _resolve_temporal(
        self, reference: str, conversation_state: Any
    ) -> Optional[ResolvedEvent]:
        """
        Resolve temporal references like 'tomorrow's meeting', 'today's 4pm event'.

        Extracts the temporal part, queries events on that date, then tries to
        match any remaining descriptive words against event titles.
        """
        ref_lower = reference.lower()

        # Check if it has a temporal pattern
        has_temporal = any(
            re.search(pattern, ref_lower) for pattern in TEMPORAL_PATTERNS
        )
        if not has_temporal:
            return None

        # Determine the target date from the temporal reference
        from tzlocal import get_localzone

        now = datetime.now(get_localzone())
        target_date = None

        if re.search(r"\btoday'?s?\b", ref_lower):
            target_date = now
        elif re.search(r"\btomorrow'?s?\b", ref_lower):
            target_date = now + timedelta(days=1)
        elif re.search(r"\byesterday'?s?\b", ref_lower):
            target_date = now - timedelta(days=1)
        elif re.search(r"\btonight'?s?\b", ref_lower):
            target_date = now.replace(hour=18, minute=0, second=0)

        if not target_date:
            # Could be "next Monday" etc. — too complex without Gemini,
            # return None and let the brain handle it via NLTimeParser
            return None

        # Fetch events on that date
        date_str = target_date.strftime("%Y-%m-%dT00:00:00")
        events = self._fetch_upcoming_events(date_hint=date_str, days_ahead=1)

        if not events:
            return None

        # If there's only one event on that date, return it
        if len(events) == 1:
            event = events[0]
            return ResolvedEvent(
                event_id=event.get("id", ""),
                title=event.get("summary", "Unknown"),
                start=self._extract_start(event),
                end=self._extract_end(event),
                strategy="temporal",
                confidence=0.85,
                raw_event=event,
            )

        # Multiple events — try to match remaining descriptive words
        # Strip temporal words to get the descriptive part
        descriptive = re.sub(
            r"\b(today'?s?|tomorrow'?s?|yesterday'?s?|tonight'?s?|this|next|the)\b",
            "",
            ref_lower,
        ).strip()

        if descriptive:
            best_match = None
            best_score = 0.0
            for event in events:
                title = event.get("summary", "").lower()
                score = SequenceMatcher(None, descriptive, title).ratio()
                if score > best_score and score >= 0.4:
                    best_score = score
                    best_match = event

            if best_match:
                return ResolvedEvent(
                    event_id=best_match.get("id", ""),
                    title=best_match.get("summary", "Unknown"),
                    start=self._extract_start(best_match),
                    end=self._extract_end(best_match),
                    strategy="temporal",
                    confidence=0.7 + (0.2 * best_score),
                    raw_event=best_match,
                )

        # Multiple events but no descriptive filter — return the next upcoming one
        event = events[0]
        return ResolvedEvent(
            event_id=event.get("id", ""),
            title=event.get("summary", "Unknown"),
            start=self._extract_start(event),
            end=self._extract_end(event),
            strategy="temporal",
            confidence=0.6,
            raw_event=event,
        )

    # ──────────────────────────────────────────────
    # Strategy 5: Contextual Reference
    # ──────────────────────────────────────────────

    def _resolve_contextual(
        self, reference: str, conversation_state: Any
    ) -> Optional[ResolvedEvent]:
        """
        Resolve contextual references like 'the one we discussed' by scanning
        recent conversation history for mentioned events.
        """
        ref_lower = reference.lower()
        is_contextual = any(
            re.search(pattern, ref_lower) for pattern in CONTEXTUAL_PATTERNS
        )

        if not is_contextual:
            return None

        # Check last_mentioned_events in conversation state
        mentioned = getattr(conversation_state, "last_mentioned_events", [])
        if mentioned:
            # Return the most recently mentioned event
            event = mentioned[-1]
            if isinstance(event, dict):
                return ResolvedEvent(
                    event_id=event.get("id", event.get("event_id", "")),
                    title=event.get("summary", event.get("title", "Unknown")),
                    start=self._extract_start(event),
                    end=self._extract_end(event),
                    strategy="contextual",
                    confidence=0.75,
                    raw_event=event,
                )

        # Fall back to last_event
        last_event = getattr(conversation_state, "last_event", None)
        if last_event and isinstance(last_event, dict):
            return ResolvedEvent(
                event_id=last_event.get("id", ""),
                title=last_event.get("summary", last_event.get("title", "Unknown")),
                start=self._extract_start(last_event),
                end=self._extract_end(last_event),
                strategy="contextual",
                confidence=0.65,
                raw_event=last_event,
            )

        return None

    # ──────────────────────────────────────────────
    # Helper Methods
    # ──────────────────────────────────────────────

    def _fetch_upcoming_events(
        self, date_hint: Optional[str] = None, days_ahead: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Fetch upcoming events from Google Calendar.

        Uses the CalendarManager's internal service to query events.
        Returns raw event dicts from the Google Calendar API.
        """
        try:
            service = self.calendar_manager._get_calendar_service()
            if not service:
                logger.warning("No calendar service available for event resolution")
                return []

            from tzlocal import get_localzone

            local_tz = get_localzone()
            now = datetime.now(local_tz)

            if date_hint:
                try:
                    # Parse date_hint
                    if isinstance(date_hint, str):
                        hint_dt = datetime.fromisoformat(
                            date_hint.replace("Z", "+00:00")
                        )
                        if hint_dt.tzinfo is None:
                            if hasattr(local_tz, "localize"):
                                hint_dt = local_tz.localize(hint_dt)
                            else:
                                hint_dt = hint_dt.replace(tzinfo=local_tz)
                        start_time = hint_dt.replace(hour=0, minute=0, second=0)
                    else:
                        start_time = now
                except (ValueError, TypeError):
                    start_time = now
            else:
                start_time = now

            end_time = start_time + timedelta(days=days_ahead)

            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_time.isoformat(),
                    timeMax=end_time.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )

            return events_result.get("items", [])

        except Exception as e:
            logger.error(f"Failed to fetch events for resolution: {e}")
            return []

    @staticmethod
    def _extract_start(event: Dict[str, Any]) -> Optional[str]:
        """Extract start datetime string from a Google Calendar event dict."""
        start = event.get("start", {})
        if isinstance(start, dict):
            return start.get("dateTime", start.get("date"))
        return str(start) if start else None

    @staticmethod
    def _extract_end(event: Dict[str, Any]) -> Optional[str]:
        """Extract end datetime string from a Google Calendar event dict."""
        end = event.get("end", {})
        if isinstance(end, dict):
            return end.get("dateTime", end.get("date"))
        return str(end) if end else None
