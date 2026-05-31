"""
Local Entity Extractor for AVA.
Rule-based extraction of times, dates, titles, and other entities
using dateutil and regex. Avoids API calls for common patterns.
"""

import re
from datetime import datetime, timedelta, time
from typing import Dict, Any, Optional, Tuple
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

from .logger import get_logger

logger = get_logger(__name__)


class EntityExtractor:
    """
    Rule-based entity extractor for calendar commands.
    Extracts: title, start_time, end_time, date, location.
    
    Supports English and Hindi/Hinglish time expressions.
    """
    
    # Common event title patterns
    TITLE_KEYWORDS = {
        'meeting': 'Meeting',
        'appointment': 'Appointment',
        'call': 'Call',
        'standup': 'Standup',
        'sync': 'Sync',
        'review': 'Review',
        'interview': 'Interview',
        'lunch': 'Lunch',
        'dinner': 'Dinner',
        'party': 'Party',
        'gym': 'Gym Session',
        'class': 'Class',
        'lecture': 'Lecture',
        'webinar': 'Webinar',
        'presentation': 'Presentation',
        'training': 'Training',
        'workshop': 'Workshop',
        'conference': 'Conference',
        'seminar': 'Seminar',
        'birthday': 'Birthday',
        'reminder': 'Reminder',
    }
    
    # Words that should NOT be captured as part of a title
    STOP_WORDS = {
        'at', 'on', 'from', 'to', 'for', 'in', 'the', 'a', 'an', 'my',
        'am', 'pm', 'tomorrow', 'today', 'next', 'this', 'with',
        'create', 'schedule', 'add', 'book', 'set', 'make', 'update',
        'change', 'modify', 'move', 'shift', 'delete', 'cancel', 'remove',
        'show', 'list', 'what', 'events', 'called', 'titled', 'named',
        # Hindi stop words
        'ko', 'ka', 'ki', 'ke', 'se', 'pe', 'par', 'mein', 'hai', 'hain',
        'karo', 'kro', 'do', 'rakh', 'rakhdo', 'banao', 'lagao', 'hatao',
        'dikha', 'dikhao', 'batao', 'baje', 'subah', 'shaam', 'raat',
        'dopahar', 'kal', 'aaj', 'agle', 'is', 'wo', 'woh',
    }
    
    # Relative day patterns
    RELATIVE_DAYS = {
        'today': 0, 'aaj': 0,
        'tomorrow': 1, 'kal': 1, 'tmrw': 1,
        'day after tomorrow': 2, 'parso': 2, 'parson': 2,
        'yesterday': -1,
    }
    
    # Day names
    DAY_NAMES = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6,
        'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6,
        'somvar': 0, 'mangalvar': 1, 'budhvar': 2, 'guruvar': 3,
        'shukravar': 4, 'shanivar': 5, 'ravivar': 6,
    }
    
    # Hindi time words
    HINDI_TIME_MAP = {
        'subah': (8, 0),   # morning default
        'dopahar': (12, 0), # afternoon default
        'shaam': (17, 0),   # evening default
        'raat': (20, 0),    # night default
    }
    
    def __init__(self, local_tz=None):
        """
        Initialize entity extractor.
        
        Args:
            local_tz: Local timezone (from tzlocal.get_localzone())
        """
        if local_tz is None:
            from tzlocal import get_localzone
            local_tz = get_localzone()
        self.local_tz = local_tz
    
    def extract(self, command: str, intent: str) -> Dict[str, Any]:
        """
        Extract entities from a command for a given intent.
        
        Args:
            command: User's natural language command
            intent: The classified intent
            
        Returns:
            Dict of extracted entities
        """
        entities = {}
        command_lower = command.lower().strip()
        
        # Extract title
        title = self._extract_title(command_lower, intent)
        if title:
            entities['title'] = title
        
        # Extract date
        target_date = self._extract_date(command_lower)
        
        # Extract time(s)
        start_time, end_time = self._extract_times(command_lower, target_date)
        
        if start_time:
            entities['start_time'] = start_time.isoformat()
        if end_time:
            entities['end_time'] = end_time.isoformat()
        
        # For read_events, extract date range
        if intent == 'read_events' and not start_time:
            start_range, end_range = self._extract_date_range(command_lower)
            if start_range:
                entities['start_time'] = start_range.isoformat()
            if end_range:
                entities['end_time'] = end_range.isoformat()
        
        logger.debug(f"Extracted entities: {entities}")
        return entities
    
    def _extract_title(self, command: str, intent: str) -> Optional[str]:
        """Extract event title from command."""
        # Pattern 1: Explicit "called X" / "titled X" / "named X"
        explicit_patterns = [
            r'(?:called|titled|named)\s+["\']?(.+?)["\']?(?:\s+(?:at|on|for|from|tomorrow|today|next)\b|$)',
            r'(?:title|naam)\s+(?:is|hai|ko)?\s*["\']?(.+?)["\']?(?:\s+(?:at|on|for|from|tomorrow|today|next)\b|$)',
        ]
        
        for pattern in explicit_patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                # Clean stop words from edges
                title = self._clean_title(title)
                if title:
                    return title.title()
        
        # Pattern 2: Multi-word title extraction around known keywords
        # e.g., "team meeting", "doctor appointment", "design sync with team"
        for keyword, default_title in self.TITLE_KEYWORDS.items():
            if keyword in command:
                title = self._extract_title_around_keyword(command, keyword)
                if title:
                    return title
                return default_title
        
        # Default for create intents
        if intent == 'create_event':
            return 'Event'
        
        return None
    
    def _extract_title_around_keyword(self, command: str, keyword: str) -> Optional[str]:
        """
        Extract a multi-word title centered around a keyword.
        Captures adjective/noun words before and after, stops at prepositions and time words.
        """
        # Split command into words
        words = command.split()
        
        # Find keyword position
        keyword_idx = None
        for i, w in enumerate(words):
            if w == keyword:
                keyword_idx = i
                break
        
        if keyword_idx is None:
            return None
        
        # Expand backwards — capture qualifying words
        start = keyword_idx
        for i in range(keyword_idx - 1, -1, -1):
            word = words[i].lower()
            if word in self.STOP_WORDS or re.match(r'^\d+$', word):
                break
            start = i
        
        # Expand forwards — capture qualifying words
        end = keyword_idx
        for i in range(keyword_idx + 1, len(words)):
            word = words[i].lower()
            if word in self.STOP_WORDS or re.match(r'^\d', word):
                break
            end = i
        
        title_words = words[start:end + 1]
        title = ' '.join(title_words).strip()
        
        # Clean and validate
        title = self._clean_title(title)
        if title and len(title) > 1:
            return title.title()
        
        return None
    
    def _clean_title(self, title: str) -> str:
        """Remove stop words from the edges of a title."""
        words = title.split()
        # Strip stop words from start
        while words and words[0].lower() in self.STOP_WORDS:
            words.pop(0)
        # Strip stop words from end
        while words and words[-1].lower() in self.STOP_WORDS:
            words.pop()
        return ' '.join(words)
    
    def _extract_date(self, command: str) -> Optional[datetime]:
        """Extract a date from the command."""
        now = datetime.now(self.local_tz)
        
        # Check relative days first
        for phrase, offset in sorted(self.RELATIVE_DAYS.items(), key=lambda x: -len(x[0])):
            if phrase in command:
                target = now + timedelta(days=offset)
                return target
        
        # Check day names ("next Monday", "this Friday")
        for day_name, day_num in self.DAY_NAMES.items():
            if day_name in command:
                current_day = now.weekday()
                days_ahead = day_num - current_day
                if days_ahead <= 0:
                    days_ahead += 7
                
                # "next" modifier adds a week
                if 'next' in command or 'agle' in command:
                    if days_ahead <= 7:
                        days_ahead += 7
                
                target = now + timedelta(days=days_ahead)
                return target
        
        # Try dateutil parser for explicit dates (with AND without year)
        date_patterns = [
            # Full dates with year
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4})',
            r'((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,\s*|\s+)\d{4})',
            # Dates WITHOUT year — "June 5th", "5th June", "June 5", "Dec 25"
            r'((?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?)',
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|august|september|october|november|december))',
            # Abbreviated months — "Jun 5th", "5th Jun"
            r'((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?)',
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))',
            # Numeric formats
            r'(\d{1,2}/\d{1,2}/\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                try:
                    parsed = dateutil_parser.parse(match.group(1), fuzzy=True, default=now)
                    # If the parsed date is in the past and no year was specified, assume next year
                    if parsed.date() < now.date():
                        # Check if the original string had a year
                        if not re.search(r'\d{4}', match.group(1)):
                            parsed = parsed.replace(year=now.year + 1)
                    return parsed.replace(tzinfo=self.local_tz)
                except (ValueError, TypeError):
                    continue
        
        # Default to today
        return now
    
    def _extract_times(self, command: str, target_date: Optional[datetime] = None) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Extract start and end times from the command."""
        now = datetime.now(self.local_tz)
        if target_date is None:
            target_date = now
        
        base_date = target_date.date()
        times_found = []
        
        # Pattern 1: "X:YY am/pm" or "X am/pm"
        time_pattern = r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)'
        matches = re.findall(time_pattern, command, re.IGNORECASE)
        
        for match in matches:
            hour = int(match[0])
            minute = int(match[1]) if match[1] else 0
            ampm = match[2].lower().replace('.', '')
            
            if ampm == 'pm' and hour != 12:
                hour += 12
            elif ampm == 'am' and hour == 12:
                hour = 0
            
            times_found.append((hour, minute))
        
        # Pattern 2: "X baje" (Hindi - X o'clock)
        baje_pattern = r'(\d{1,2})(?::(\d{2}))?\s*baje'
        baje_matches = re.findall(baje_pattern, command, re.IGNORECASE)
        
        for match in baje_matches:
            hour = int(match[0])
            minute = int(match[1]) if match[1] else 0
            
            # Contextual AM/PM for Hindi
            if 'subah' in command and hour <= 12:
                pass  # morning, keep as-is
            elif 'shaam' in command or 'dopahar' in command:
                if hour < 12:
                    hour += 12
            elif 'raat' in command:
                if hour < 12:
                    hour += 12
            elif hour < 7:
                # Ambiguous small numbers — assume PM for typical meeting times
                hour += 12
            
            times_found.append((hour, minute))
        
        # Pattern 3: 24-hour format "14:00"
        twenty_four_pattern = r'(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\s*(?:am|pm|baje))'
        twenty_four_matches = re.findall(twenty_four_pattern, command, re.IGNORECASE)
        
        for match in twenty_four_matches:
            hour = int(match[0])
            minute = int(match[1])
            if hour >= 7:  # Filter out random number pairs
                times_found.append((hour, minute))
        
        # Pattern 4: "noon" / "midnight"
        if 'noon' in command or 'dopahar' in command:
            if not times_found:
                times_found.append((12, 0))
        if 'midnight' in command or 'aadhi raat' in command:
            if not times_found:
                times_found.append((0, 0))
        
        # Build datetime objects
        if len(times_found) >= 2:
            start_h, start_m = times_found[0]
            end_h, end_m = times_found[1]
            
            start_dt = datetime.combine(base_date, time(start_h, start_m)).replace(tzinfo=self.local_tz)
            end_dt = datetime.combine(base_date, time(end_h, end_m)).replace(tzinfo=self.local_tz)
            
            return start_dt, end_dt
            
        elif len(times_found) == 1:
            start_h, start_m = times_found[0]
            start_dt = datetime.combine(base_date, time(start_h, start_m)).replace(tzinfo=self.local_tz)
            # Default: 1 hour duration
            end_dt = start_dt + timedelta(hours=1)
            
            return start_dt, end_dt
        
        # No times found
        return None, None
    
    def _extract_date_range(self, command: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Extract a date range for read_events queries.
        
        Handles past, present, and future temporal expressions including:
        - yesterday, last week, last month, last N days, past week
        - today, this week, this month, weekend
        - tomorrow, next week
        - explicit date ranges (between X and Y, from X to Y)
        """
        now = datetime.now(self.local_tz)
        
        # ── Past-oriented expressions (checked first) ──────────────
        
        # "yesterday" / "kal beet gaya" / "kal ka"
        if any(p in command for p in ['yesterday', 'kal beet gaya', 'kal ka', 'kal ke']):
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end = yesterday.replace(hour=23, minute=59, second=59)
            return start, end
        
        # "last N days" e.g. "last 3 days", "last 30 days"
        match = re.search(r'last\s+(\d+)\s+days?', command)
        if match:
            n = int(match.group(1))
            end = now
            start = (now - timedelta(days=n)).replace(hour=0, minute=0, second=0, microsecond=0)
            return start, end
        
        # "last week" / "pichle hafte" / "pichla hafta" / "past week"
        if any(p in command for p in ['last week', 'pichle hafte', 'pichla hafta', 'past week']):
            days_since_monday = now.weekday()
            # Start of previous week (Monday)
            start = (now - timedelta(days=days_since_monday + 7)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (start + timedelta(days=6)).replace(hour=23, minute=59, second=59)
            return start, end
        
        # "last month" / "pichle mahine"
        if any(p in command for p in ['last month', 'pichle mahine', 'pichla mahina']):
            first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = (first_of_this_month - timedelta(seconds=1))
            start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return start, end
        
        # ── Explicit date ranges (between X and Y, from X to Y) ────
        
        date_patterns = [
            # American Style: Month Day, Year / Month Day
            r'((?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,\s*|\s+)\d{4})',
            r'((?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{1,2}(?:st|nd|rd|th)?)',
            # British/European Style: Day Month Year / Day Month
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4})',
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4})',
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:january|february|march|april|may|june|july|august|september|october|november|december))',
            r'(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))',
            # Numeric formats
            r'(\d{1,2}/\d{1,2}/\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})',
        ]
        
        combined_pattern = '|'.join(date_patterns)
        matches = re.finditer(combined_pattern, command, re.IGNORECASE)
        dates_found = []
        for m in matches:
            date_str = m.group(0)
            try:
                parsed = dateutil_parser.parse(date_str, default=now)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=self.local_tz)
                dates_found.append(parsed)
            except (ValueError, TypeError):
                continue
        
        if len(dates_found) >= 2:
            dates_found.sort()
            start = dates_found[0].replace(hour=0, minute=0, second=0, microsecond=0)
            end = dates_found[-1].replace(hour=23, minute=59, second=59)
            return start, end
        elif len(dates_found) == 1:
            start = dates_found[0].replace(hour=0, minute=0, second=0, microsecond=0)
            end = dates_found[0].replace(hour=23, minute=59, second=59)
            return start, end
        
        # ── Present / future relative expressions ──────────────────
        
        # "this week" / "is hafte"
        if 'this week' in command or 'is hafte' in command or 'is week' in command:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # End of week (Sunday)
            days_until_sunday = 6 - now.weekday()
            end = (now + timedelta(days=days_until_sunday)).replace(hour=23, minute=59, second=59)
            return start, end
        
        # "next week" / "agle hafte"
        if 'next week' in command or 'agle hafte' in command or 'agli week' in command:
            days_until_monday = 7 - now.weekday()
            start = (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (start + timedelta(days=6)).replace(hour=23, minute=59, second=59)
            return start, end
        
        # "today" / "aaj"
        if 'today' in command or 'aaj' in command:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59)
            return start, end
        
        # "tomorrow" / "kal" (only when not caught by yesterday patterns above)
        if 'tomorrow' in command or ('kal' in command and 'beet' not in command):
            tomorrow = now + timedelta(days=1)
            start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end = tomorrow.replace(hour=23, minute=59, second=59)
            return start, end
        
        # "this month" / "is mahine"
        if 'this month' in command or 'is mahine' in command:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = start + relativedelta(months=1)
            end = (next_month - timedelta(days=1)).replace(hour=23, minute=59, second=59)
            return start, end
        
        # "weekend"
        if 'weekend' in command:
            days_until_saturday = 5 - now.weekday()
            if days_until_saturday < 0:
                days_until_saturday += 7
            start = (now + timedelta(days=days_until_saturday)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (start + timedelta(days=1)).replace(hour=23, minute=59, second=59)
            return start, end
        
        # Default: next 7 days
        start = now
        end = now + timedelta(days=7)
        return start, end
