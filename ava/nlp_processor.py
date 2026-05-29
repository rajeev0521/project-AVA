"""
NLP Processor for AVA.
Handles intent extraction, entity parsing, and response generation.
Uses a two-tier system: local intent classifier (fast) → Gemini API (fallback).
"""

import os
import json
from datetime import datetime
import re
from dotenv import load_dotenv
from tzlocal import get_localzone
from typing import Optional, Dict, Any, Tuple

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from logger import get_logger

logger = get_logger(__name__)


class CalendarIntent(BaseModel):
    """Structured output schema for Gemini intent extraction."""
    intent: Optional[str] = Field(
        description="The intent of the user. One of: create_event, read_events, update_event, delete_event"
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities like title, start_time, end_time (in ISO 8601 with timezone), event_id, etc."
    )
    response_template: str = Field(
        default="",
        description="A brief, natural confirmation phrase to say back to the user after the action is performed"
    )


# Hindi character ranges and common Hindi/Hinglish words for language detection
_HINDI_CHARS = re.compile(r'[\u0900-\u097F]')  # Devanagari Unicode block
_HINDI_MARKERS = {
    'karo', 'kro', 'hai', 'hain', 'mera', 'meri', 'mere', 'kya', 'kab',
    'kal', 'aaj', 'baje', 'subah', 'shaam', 'raat', 'dopahar', 'parso',
    'dikha', 'dikhao', 'batao', 'hatao', 'nikalo', 'lagao', 'banao',
    'rakh', 'badlo', 'haan', 'nahi', 'nhi', 'acha', 'theek', 'sab',
    'woh', 'usse', 'isko', 'usko', 'ke', 'ki', 'ka', 'mein', 'ko',
    'se', 'pe', 'par', 'bhi', 'aur', 'ya', 'wala', 'wali', 'do',
    'hafte', 'mahine', 'saal', 'ghanta', 'minute',
}

# Dynamic tone mapping based on intent
_INTENT_TONE_MAP = {
    'create_event': 'professional',     # Scheduling = crisp & professional
    'read_events': 'friendly',          # Listing = warm & friendly
    'update_event': 'helpful',          # Modifying = supportive & helpful
    'delete_event': 'careful',          # Deleting = cautious & confirming
}


class NLPProcessor:
    def __init__(self, user_name=None, memory_manager=None):
        """
        Initialize NLP Processor.
        
        Args:
            user_name: User's display name (from frontend/auth, not env).
                       If None, defaults to a polite generic address.
            memory_manager: Optional MemoryManager instance for conversational context
        """
        # Configure env
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        # Initialize LangChain model — single instance, reused everywhere
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=api_key,
            temperature=0.0
        )
        
        # Structured output parser for intent
        self.intent_parser = self.llm.with_structured_output(CalendarIntent)
        
        # Get local timezone
        self.local_tz = get_localzone()

        # Username from frontend/auth — NOT from env
        self.user_name = user_name or "there"

        # Language and tone are DYNAMIC — detected per-command
        # These are set per-call, not at init time
        self._detected_language = "English"
        self._dynamic_tone = "friendly"

        # Memory manager for conversational context
        self.memory = memory_manager

        # Load system prompt from file
        prompt_path = os.path.join(os.path.dirname(__file__), 'system_prompt.txt')
        with open(prompt_path, 'r') as f:
            self.system_prompt_template = f.read()

        # Intent extraction prompt (includes conversation history slot)
        self.intent_prompt = PromptTemplate.from_template(
            "{system_prompt}\n\n"
            "## Conversation History (most recent):\n{conversation_history}\n\n"
            "## Response Settings:\n"
            "- Respond in: {language}\n"
            "- Tone: {tone}\n"
            "- User's name: {user_name}\n\n"
            "User command: {command}"
        )

        # Local intent classifier (lazy loaded)
        self._intent_classifier = None
        self._entity_extractor = None
        
        logger.info(f"NLPProcessor initialized (model=gemini-2.0-flash, user={self.user_name})")
    
    def set_user_name(self, name: str):
        """Update username dynamically (called when user logs in / sets name from UI)."""
        self.user_name = name or "there"
        logger.info(f"Username updated to: {self.user_name}")
    
    @staticmethod
    def detect_language(text: str) -> str:
        """
        Auto-detect whether the user is speaking English, Hindi, or Hinglish.
        
        Detection logic:
        1. If Devanagari script characters present → Hindi
        2. Count Hindi/Hinglish marker words vs total words
        3. If >40% Hindi markers → Hindi, 15-40% → Hinglish, else → English
        
        Returns: "Hindi", "Hinglish", or "English"
        """
        # Check for Devanagari script
        if _HINDI_CHARS.search(text):
            return "Hindi"
        
        words = set(re.findall(r'[a-zA-Z]+', text.lower()))
        if not words:
            return "English"
        
        hindi_count = len(words & _HINDI_MARKERS)
        ratio = hindi_count / len(words)
        
        if ratio > 0.4:
            return "Hindi"
        elif ratio > 0.15:
            return "Hinglish"
        else:
            return "English"
    
    @staticmethod
    def get_dynamic_tone(intent: Optional[str]) -> str:
        """
        Select response tone dynamically based on intent.
        
        - create_event → professional (scheduling should feel crisp)
        - read_events  → friendly (information sharing is warm)
        - update_event → helpful (changes need supportive language)
        - delete_event → careful (destructive actions need caution)
        - unknown      → friendly (default)
        """
        return _INTENT_TONE_MAP.get(intent, 'friendly')
        
    @property
    def intent_classifier(self):
        """Lazy-load the local intent classifier."""
        if self._intent_classifier is None:
            try:
                from intent_classifier import IntentClassifier
                self._intent_classifier = IntentClassifier()
                logger.info("Local intent classifier loaded")
            except ImportError:
                logger.warning("IntentClassifier not available, using Gemini-only mode")
                self._intent_classifier = None
        return self._intent_classifier
    
    @property
    def entity_extractor(self):
        """Lazy-load the local entity extractor."""
        if self._entity_extractor is None:
            try:
                from entity_extractor import EntityExtractor
                self._entity_extractor = EntityExtractor(self.local_tz)
                logger.info("Local entity extractor loaded")
            except ImportError:
                logger.warning("EntityExtractor not available, using Gemini-only mode")
                self._entity_extractor = None
        return self._entity_extractor
        
    def _get_system_prompt(self):
        """Formats the system prompt with dynamic data."""
        now = datetime.now(self.local_tz)
        return self.system_prompt_template.format(
            local_tz=str(self.local_tz),
            current_date_time=now.strftime('%Y-%m-%d %H:%M:%S %Z'),
            current_date=now.strftime('%Y-%m-%d')
        )

    def _get_conversation_history(self) -> str:
        """Get formatted conversation history from memory manager."""
        if self.memory:
            try:
                return self.memory.get_context_prompt()
            except Exception as e:
                logger.warning(f"Failed to get conversation history: {e}")
        return "No previous conversation."

    def process_command(self, command: str) -> Tuple[Optional[str], Dict[str, Any], str]:
        """
        Process natural language command. Returns (intent, entities, response_template).
        
        Uses two-tier approach:
        1. Local classifier (fast, ~5ms) if confidence >= 0.85
        2. Gemini API fallback (slower, ~1-3s) for uncertain commands
        
        Args:
            command: The user's natural language command
            
        Returns:
            Tuple of (intent, entities_dict, response_template)
        """
        # Step 1: Detect language from user's input
        self._detected_language = self.detect_language(command)
        logger.info(f"Detected language: {self._detected_language}")

        # Step 2: Resolve references if memory is available
        resolved_command = command
        if self.memory:
            try:
                resolved_command = self.memory.resolve_reference(command)
                if resolved_command != command:
                    logger.info(f"Reference resolved: '{command}' → '{resolved_command}'")
            except Exception as e:
                logger.warning(f"Reference resolution failed: {e}")

        # Tier 1: Try local intent classifier first (~5ms)
        if self.intent_classifier is not None:
            try:
                intent, confidence = self.intent_classifier.classify(resolved_command)
                logger.info(f"Local classifier: intent={intent}, confidence={confidence:.3f}")
                
                # Set dynamic tone based on detected intent
                self._dynamic_tone = self.get_dynamic_tone(intent)
                
                if confidence >= 0.85 and self.entity_extractor is not None:
                    entities = self.entity_extractor.extract(resolved_command, intent)
                    if self._entities_are_complete(intent, entities):
                        response_template = self._local_response_template(intent, entities)
                        logger.info(f"Using local classification (skipped API call)")
                        return intent, entities, response_template
                    else:
                        logger.info(f"Local entities incomplete, falling through to Gemini")
            except Exception as e:
                logger.warning(f"Local classifier error: {e}")

        # Tier 2: Fall back to Gemini API
        return self._gemini_extract(resolved_command)

    def _gemini_extract(self, command: str) -> Tuple[Optional[str], Dict[str, Any], str]:
        """Extract intent and entities using Gemini API."""
        try:
            system_prompt = self._get_system_prompt()
            conversation_history = self._get_conversation_history()
            
            chain = self.intent_prompt | self.intent_parser
            result = chain.invoke({
                "system_prompt": system_prompt,
                "conversation_history": conversation_history,
                "command": command,
                "language": self._detected_language,
                "tone": self._dynamic_tone,
                "user_name": self.user_name,
            })
            
            if not result or not result.intent:
                logger.warning(f"Gemini returned no intent for: {command}")
                return self._fallback_parsing(command)

            intent = result.intent
            entities = result.entities or {}
            response_template = result.response_template or ""
            
            # Set dynamic tone based on the extracted intent
            self._dynamic_tone = self.get_dynamic_tone(intent)

            # Validate and fix time formats
            entities = self._validate_and_fix_times(entities)

            logger.info(f"Gemini extracted: intent={intent}, entities={list(entities.keys())}")
            return intent, entities, response_template

        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            intent, entities = self._fallback_parsing(command)
            response_template = self._local_response_template(intent, entities) if intent else ""
            return intent, entities, response_template

    def _entities_are_complete(self, intent: str, entities: Dict[str, Any]) -> bool:
        """Check if extracted entities are sufficient for the given intent."""
        if intent == "create_event":
            return all(k in entities for k in ['title', 'start_time', 'end_time'])
        elif intent == "read_events":
            return True  # No required entities
        elif intent == "delete_event":
            return 'title' in entities or 'event_id' in entities or 'start_time' in entities
        elif intent == "update_event":
            return ('title' in entities or 'event_id' in entities)
        return False

    def _local_response_template(self, intent: Optional[str], entities: Dict[str, Any]) -> str:
        """Generate a response template locally without API call. Language-aware."""
        if not intent:
            if self._detected_language in ("Hindi", "Hinglish"):
                return "Maaf kijiye, aapka request samajh nahi aaya."
            return "I couldn't understand your request."
        
        title = entities.get('title', 'your event')
        name = self.user_name
        lang = self._detected_language
        
        if lang in ("Hindi", "Hinglish"):
            templates = {
                "create_event": f"Done! {name}, maine '{title}' schedule kar diya hai.",
                "read_events": f"{name}, yeh hain aapke upcoming events.",
                "update_event": f"Ho gaya! {name}, maine '{title}' update kar diya.",
                "delete_event": f"Done! {name}, maine '{title}' calendar se hata diya.",
            }
        else:
            templates = {
                "create_event": f"Done! {name}, I've scheduled '{title}' for you.",
                "read_events": f"Here are your upcoming events, {name}.",
                "update_event": f"Got it! {name}, I've updated '{title}'.",
                "delete_event": f"Done! {name}, I've removed '{title}' from your calendar.",
            }
        return templates.get(intent, "Your request has been processed.")

    def _validate_and_fix_times(self, entities):
        """Validate and fix time formats to ensure they're in local timezone"""
        for time_key in ['start_time', 'end_time']:
            if time_key in entities:
                time_str = entities[time_key]
                if not isinstance(time_str, str):
                    continue
                try:
                    # Parse the time string
                    if 'Z' in time_str:
                        # Convert from UTC to local time
                        dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                        dt = dt.astimezone(self.local_tz)
                    else:
                        # Try to parse as ISO format
                        dt = datetime.fromisoformat(time_str)
                        # If no timezone info, assume local timezone
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=self.local_tz)
                    
                    # Convert back to ISO format with local timezone
                    entities[time_key] = dt.isoformat()
                    
                except ValueError as e:
                    logger.warning(f"Error parsing time {time_str}: {e}")
                    # Keep original if parsing fails
                    
        return entities

    def _fallback_parsing(self, command):
        """Enhanced fallback parsing when LangChain extraction fails"""
        command_lower = command.lower()

        # Determine intent
        if any(word in command_lower for word in ['delete', 'cancel', 'remove', 'hatao', 'nikalo']):
            intent = 'delete_event'
        elif any(word in command_lower for word in ['update', 'change', 'modify', 'badlo', 'shift']):
            intent = 'update_event'
        elif any(word in command_lower for word in ['show', 'list', 'what', 'events', 'dikha', 'batao', 'kya']):
            intent = 'read_events'
        elif any(word in command_lower for word in ['schedule', 'create', 'add', 'book', 'banao', 'lagao', 'set']):
            intent = 'create_event'
        else:
            return None, {}

        # Extract basic entities for create_event
        entities = {}
        if intent == 'create_event':
            # Extract title
            if 'meeting' in command_lower:
                entities['title'] = 'Meeting'
            elif 'appointment' in command_lower:
                entities['title'] = 'Appointment'
            else:
                entities['title'] = 'Event'

            # Try to extract times with regex
            time_patterns = [
                r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)'
            ]
            
            times_found = []
            for pattern in time_patterns:
                matches = re.findall(pattern, command_lower, re.IGNORECASE)
                for match in matches:
                    hour = int(match[0])
                    minute = int(match[1]) if match[1] else 0
                    ampm = match[2].lower()
                    
                    if ampm in ['pm', 'p.m.'] and hour != 12:
                        hour += 12
                    elif ampm in ['am', 'a.m.'] and hour == 12:
                        hour = 0
                    
                    times_found.append((hour, minute))
            
            # Extract date
            date_today = datetime.now(self.local_tz).date()
            
            # Look for date patterns
            date_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)\s+(\d{4})', command_lower)
            if date_match:
                day = int(date_match.group(1))
                month_name = date_match.group(2)
                year = int(date_match.group(3))
                
                # Convert month name to number
                month_names = {
                    'january': 1, 'jan': 1, 'february': 2, 'feb': 2,
                    'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
                    'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
                    'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
                    'october': 10, 'oct': 10, 'november': 11, 'nov': 11,
                    'december': 12, 'dec': 12
                }
                month = month_names.get(month_name.lower(), date_today.month)
                event_date = datetime(year, month, day).date()
            else:
                event_date = date_today
            
            # Set times
            if len(times_found) >= 2:
                start_hour, start_minute = times_found[0]
                end_hour, end_minute = times_found[1]
                
                start_dt = datetime.combine(event_date, datetime.min.time().replace(hour=start_hour, minute=start_minute)).replace(tzinfo=self.local_tz)
                end_dt = datetime.combine(event_date, datetime.min.time().replace(hour=end_hour, minute=end_minute)).replace(tzinfo=self.local_tz)
                
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()
            elif len(times_found) == 1:
                start_hour, start_minute = times_found[0]
                start_dt = datetime.combine(event_date, datetime.min.time().replace(hour=start_hour, minute=start_minute)).replace(tzinfo=self.local_tz)
                end_dt = datetime.combine(event_date, datetime.min.time().replace(hour=start_hour + 1, minute=start_minute)).replace(tzinfo=self.local_tz)
                
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()
            else:
                # Default times
                start_dt = datetime.combine(event_date, datetime.min.time().replace(hour=14, minute=0)).replace(tzinfo=self.local_tz)
                end_dt = datetime.combine(event_date, datetime.min.time().replace(hour=15, minute=0)).replace(tzinfo=self.local_tz)
                
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()

        return intent, entities

    def generate_response(self, action_result: str, intent: str = None, 
                          entities: dict = None, response_template: str = "") -> str:
        """
        Generate a natural language response for the user.
        
        Uses the response_template from the initial LLM call when available,
        avoiding a second API call entirely. Falls back to static templates.
        
        Args:
            action_result: The result string from the calendar action
            intent: The detected intent
            entities: The extracted entities
            response_template: Pre-generated template from the LLM (avoids 2nd API call)
            
        Returns:
            Natural language response string
        """
        try:
            # If we have a response template from the LLM, use it (no API call needed)
            if response_template and "error" not in action_result.lower():
                # Personalize the template
                response = response_template.replace("{user_name}", self.user_name)
                logger.info("Using pre-generated response template (no API call)")
                return response
            
            # For errors or missing template, use local generation
            return self._local_generate_response(action_result, intent, entities)
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I've completed your request."

    def _local_generate_response(self, action_result: str, intent: str = None, 
                                  entities: dict = None) -> str:
        """Generate response locally without any API call. Bilingual & tone-aware."""
        name = self.user_name
        lang = self._detected_language
        is_hindi = lang in ("Hindi", "Hinglish")
        
        if entities:
            # Format times for display
            display_entities = entities.copy()
            for time_key in ['start_time', 'end_time']:
                if time_key in display_entities:
                    try:
                        dt = datetime.fromisoformat(str(display_entities[time_key]))
                        display_entities[time_key] = dt.strftime('%B %d, %Y at %I:%M %p')
                    except (ValueError, TypeError):
                        pass

            title = display_entities.get('title', 'your event')
            start = display_entities.get('start_time', '')
            
            if intent == "create_event":
                if is_hindi:
                    return f"{name}, maine '{title}' ko {start} pe schedule kar diya hai."
                return f"{name}, I've successfully created '{title}' on {start}."
            elif intent == "update_event":
                if is_hindi:
                    return f"{name}, maine '{title}' update kar diya hai."
                return f"{name}, I've updated '{title}'."
            elif intent == "delete_event":
                if is_hindi:
                    return f"{name}, maine '{title}' delete kar diya hai."
                return f"{name}, I've deleted '{title}'."
            elif intent == "read_events":
                return action_result

        # Generic fallback — bilingual
        result_lower = action_result.lower()
        if "created" in result_lower:
            if is_hindi:
                return f"{name}, aapka event successfully create ho gaya hai."
            return f"{name}, I've successfully created your event."
        elif "error" in result_lower:
            if is_hindi:
                return f"Sorry {name}, ek problem aayi hai: {action_result}"
            return f"Sorry {name}, there was an issue: {action_result}"
        elif "updated" in result_lower:
            if is_hindi:
                return f"{name}, aapka event update ho gaya hai."
            return f"{name}, I've updated your event."
        elif "deleted" in result_lower:
            if is_hindi:
                return f"{name}, event delete ho gaya hai."
            return f"{name}, I've deleted the event."
        elif "no upcoming events" in result_lower or "no events found" in result_lower:
            if is_hindi:
                return f"{name}, aapke koi upcoming events nahi hain."
            return f"{name}, you don't have any upcoming events."
        else:
            return action_result