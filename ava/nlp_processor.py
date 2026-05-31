"""
NLP Processor for AVA.
Handles intent extraction, entity parsing, and response generation.
Uses a two-tier system: local intent classifier (fast) → Gemini API (fallback).
"""

import os
import json
import re
import html
from datetime import datetime
from dotenv import load_dotenv
from tzlocal import get_localzone
from typing import Optional, Dict, Any, Tuple

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

from .logger import get_logger

try:
    from .intent_classifier import IntentClassifier
    from .entity_extractor import EntityExtractor
except ImportError:
    IntentClassifier = None
    EntityExtractor = None

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

# Greeting patterns
_GREETING_PATTERNS = [
    'hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening',
    'how are you', 'what\'s up', 'whats up', 'howdy', 'yo', 'sup',
    'namaste', 'namaskar', 'kaise ho', 'kya haal', 'kya hal',
]

# Off-topic patterns (not calendar related)
_OFF_TOPIC_PATTERNS = [
    'weather', 'news', 'joke', 'tell me a joke', 'song', 'play',
    'calculator', 'math', 'translate', 'define', 'meaning of',
    'who is', 'what is the capital', 'how to cook',
]


def sanitize_user_input(text: str) -> str:
    """
    Sanitize user input to prevent XSS when reflected in responses.
    Escapes HTML special characters.
    """
    return html.escape(text, quote=True)


class NLPProcessor:
    def __init__(self, user_name=None, memory_manager=None, llm=None, user_timezone=None):
        """
        Initialize NLP Processor.
        
        Args:
            user_name: User's display name (from frontend/auth, not env).
                       If None, defaults to a polite generic address.
            memory_manager: Optional MemoryManager instance for conversational context
            llm: Optional shared ChatGoogleGenerativeAI instance. If None, creates one.
            user_timezone: User's timezone string from the client (e.g., 'Asia/Kolkata').
                          Falls back to server timezone if not provided.
        """
        # Configure env
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        # Use shared LLM instance if provided, otherwise create one
        if llm is not None:
            self.llm = llm
        else:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=api_key,
                temperature=0.0
            )
        
        # Structured output parser for intent
        self.intent_parser = self.llm.with_structured_output(CalendarIntent)
        
        # Use client timezone if provided, otherwise fall back to server timezone
        if user_timezone:
            import pytz
            try:
                self.local_tz = pytz.timezone(user_timezone)
            except pytz.UnknownTimeZoneError:
                logger.warning(f"Unknown timezone '{user_timezone}', falling back to server timezone")
                self.local_tz = get_localzone()
        else:
            self.local_tz = get_localzone()

        # Username — sanitize to prevent XSS (Bug #10)
        self.user_name = sanitize_user_input(user_name) if user_name else "there"

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
        
        logger.info(f"NLPProcessor initialized (model=gemini-2.0-flash, user={self.user_name}, tz={self.local_tz})")
    
    def set_user_name(self, name: str):
        """Update username dynamically (called when user logs in / sets name from UI)."""
        self.user_name = sanitize_user_input(name) if name else "there"
        logger.info(f"Username updated to: {self.user_name}")
    
    def set_timezone(self, timezone_str: str):
        """Update timezone from client-provided value."""
        if timezone_str:
            import pytz
            try:
                self.local_tz = pytz.timezone(timezone_str)
                logger.info(f"Timezone updated to: {self.local_tz}")
            except pytz.UnknownTimeZoneError:
                logger.warning(f"Unknown timezone '{timezone_str}', keeping current: {self.local_tz}")
    
    @staticmethod
    def detect_language(text: str) -> str:
        """
        Auto-detect whether the user is speaking English, Hindi, or Hinglish.
        
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
        """Select response tone dynamically based on intent."""
        return _INTENT_TONE_MAP.get(intent, 'friendly')
    
    @staticmethod
    def is_greeting(command: str) -> bool:
        """Check if the command is a greeting."""
        cmd_lower = command.lower().strip()
        return any(pattern in cmd_lower for pattern in _GREETING_PATTERNS)
    
    @staticmethod
    def is_off_topic(command: str) -> bool:
        """Check if the command is off-topic (not calendar related)."""
        cmd_lower = command.lower().strip()
        return any(pattern in cmd_lower for pattern in _OFF_TOPIC_PATTERNS)
        
    @property
    def intent_classifier(self):
        """Lazy-load the local intent classifier."""
        if self._intent_classifier is None and IntentClassifier is not None:
            try:
                self._intent_classifier = IntentClassifier()
                logger.info("Local intent classifier loaded")
            except Exception as e:
                logger.warning(f"IntentClassifier init failed: {e}")
        return self._intent_classifier
    
    @property
    def entity_extractor(self):
        """Lazy-load the local entity extractor."""
        if self._entity_extractor is None and EntityExtractor is not None:
            try:
                self._entity_extractor = EntityExtractor(self.local_tz)
                logger.info("Local entity extractor loaded")
            except Exception as e:
                logger.warning(f"EntityExtractor init failed: {e}")
        return self._entity_extractor
        
    def _get_system_prompt(self):
        """Formats the system prompt with dynamic data."""
        now = datetime.now(self.local_tz)
        prompt = self.system_prompt_template
        prompt = prompt.replace("{local_tz}", str(self.local_tz))
        prompt = prompt.replace("{current_date_time}", now.strftime('%Y-%m-%d %H:%M:%S %Z'))
        prompt = prompt.replace("{current_date}", now.strftime('%Y-%m-%d'))
        return prompt

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
        
        Handles greetings and off-topic queries before NLP processing.
        Uses two-tier approach for calendar commands:
        1. Local classifier (fast, ~5ms) if confidence >= 0.80
        2. Gemini API full extraction (slower, ~1-3s) for uncertain commands
        """
        # Step 0: Handle greetings and off-topic queries (Bug #6, #7)
        if self.is_greeting(command):
            detected_lang = self.detect_language(command)
            if detected_lang in ("Hindi", "Hinglish"):
                greeting = f"Namaste {self.user_name}! Main AVA hoon, aapki AI calendar assistant. Aap mujhse apne schedule ke baare mein pooch sakte hain ya events create, update, delete kar sakte hain."
            else:
                greeting = f"Hi {self.user_name}! I'm AVA, your AI calendar assistant. You can ask me to show your schedule, create events, update or delete them. How can I help you today?"
            return None, {}, greeting
        
        if self.is_off_topic(command):
            detected_lang = self.detect_language(command)
            if detected_lang in ("Hindi", "Hinglish"):
                return None, {}, f"Sorry {self.user_name}, main sirf calendar se related kaam kar sakti hoon. Kya aap koi event create, dekhna, update ya delete karna chahte hain?"
            return None, {}, f"Sorry {self.user_name}, I can only help with calendar-related tasks. Would you like to create, view, update, or delete an event?"

        # Step 1: Detect language from user's input
        detected_language = self.detect_language(command)
        logger.info(f"Detected language: {detected_language}")

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
                dynamic_tone = self.get_dynamic_tone(intent)
                
                if confidence >= 0.80:
                    # Intent is determined locally. Now try entity extraction.
                    if self.entity_extractor is not None:
                        entities = self.entity_extractor.extract(resolved_command, intent)
                    else:
                        entities = {}
                    
                    # Check if we have enough entities to execute
                    if self._can_execute_with_entities(intent, entities):
                        response_template = self._local_response_template(intent, entities, detected_language)
                        logger.info("Full local resolution — no API call")
                        return intent, entities, response_template
                    else:
                        # Partial local: we know the intent, ask Gemini only for entities
                        logger.info(f"Intent local ({confidence:.2f}), sending to Gemini for entity extraction only")
                        return self._gemini_extract_entities_only(resolved_command, intent, detected_language, dynamic_tone)
            except Exception as e:
                logger.warning(f"Local classifier error: {e}")

        # Tier 2: Fall back to Gemini API for full extraction
        return self._gemini_extract(resolved_command, detected_language)

    def _gemini_extract(self, command: str, detected_language: str = "English") -> Tuple[Optional[str], Dict[str, Any], str]:
        """Extract intent and entities using Gemini API."""
        try:
            system_prompt = self._get_system_prompt()
            conversation_history = self._get_conversation_history()
            dynamic_tone = "friendly"
            
            chain = self.intent_prompt | self.intent_parser
            result = chain.invoke({
                "system_prompt": system_prompt,
                "conversation_history": conversation_history,
                "command": command,
                "language": detected_language,
                "tone": dynamic_tone,
                "user_name": self.user_name,
            })
            
            if not result or not result.intent:
                logger.warning(f"Gemini returned no intent for: {command}")
                return self._fallback_parsing(command, detected_language)

            intent = result.intent
            entities = result.entities or {}
            response_template = result.response_template or ""
            
            # Set dynamic tone based on the extracted intent
            dynamic_tone = self.get_dynamic_tone(intent)

            # Validate and fix time formats
            entities = self._validate_and_fix_times(entities)

            logger.info(f"Gemini extracted: intent={intent}, entities={list(entities.keys())}")
            return intent, entities, response_template

        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            intent, entities = self._fallback_parsing(command, detected_language)
            response_template = self._local_response_template(intent, entities, detected_language) if intent else ""
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

    def _can_execute_with_entities(self, intent: str, entities: Dict[str, Any]) -> bool:
        """
        Relaxed entity check — determines if the command can be executed
        with the entities we have, using sensible defaults where possible.
        """
        if intent == "read_events":
            return True  # Always executable — defaults to 7-day window
        if intent == "delete_event":
            return bool(
                entities.get("title") or
                entities.get("start_time") or
                entities.get("event_id")
            )
        if intent == "create_event":
            return bool(entities.get("start_time"))
        if intent == "update_event":
            return bool(
                entities.get("title") or
                entities.get("event_id")
            )
        return False

    def _gemini_extract_entities_only(
        self, command: str, local_intent: str, detected_language: str = "English", dynamic_tone: str = "friendly"
    ) -> Tuple[Optional[str], Dict[str, Any], str]:
        """
        Use Gemini only for entity extraction, preserving the locally classified intent.
        """
        try:
            system_prompt = self._get_system_prompt()
            conversation_history = self._get_conversation_history()
            
            chain = self.intent_prompt | self.intent_parser
            result = chain.invoke({
                "system_prompt": system_prompt,
                "conversation_history": conversation_history,
                "command": command,
                "language": detected_language,
                "tone": dynamic_tone,
                "user_name": self.user_name,
            })
            
            if result and result.entities:
                entities = self._validate_and_fix_times(result.entities)
            else:
                entities = {}
            
            response_template = result.response_template if result else ""
            
            logger.info(f"Gemini entity extraction: intent={local_intent} (local), entities={list(entities.keys())}")
            return local_intent, entities, response_template or ""
            
        except Exception as e:
            logger.error(f"Gemini entity extraction failed: {e}")
            # Fall back to whatever entities the local extractor got
            if self.entity_extractor is not None:
                entities = self.entity_extractor.extract(command, local_intent)
            else:
                entities = {}
            response_template = self._local_response_template(local_intent, entities, detected_language)
            return local_intent, entities, response_template

    def _local_response_template(self, intent: Optional[str], entities: Dict[str, Any], detected_language: str = "English") -> str:
        """Generate a response template locally without API call. Language-aware."""
        if not intent:
            if detected_language in ("Hindi", "Hinglish"):
                return "Maaf kijiye, aapka request samajh nahi aaya."
            return "I couldn't understand your request."
        
        title = entities.get('title', 'your event')
        name = self.user_name
        is_hindi = detected_language in ("Hindi", "Hinglish")
        
        if is_hindi:
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

    def _fallback_parsing(self, command, detected_language: str = "English"):
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
        
        IMPORTANT: Never prepends a positive template when the action_result
        signals empty results, errors, or auth requirements.
        """
        try:
            # Detect error/empty/auth conditions in action_result (Bug #2 fix)
            result_lower = action_result.lower()
            is_negative_result = any(p in result_lower for p in [
                "no events found", "no upcoming events", "couldn't find",
                "error", "warning", "failed", "couldn't understand",
                "no events", "could not identify", "please sign in",
                "sign in with google", "permission denied", "not found",
            ])
            
            # If action_result signals an error/auth issue, return it directly
            # Do NOT prepend a success template like "Here are your events"
            if is_negative_result:
                return action_result
            
            # If we have a response template AND result is positive, use the template
            if response_template:
                # Personalize the template
                response = response_template.replace("{user_name}", self.user_name)
                logger.info("Using pre-generated response template (no API call)")
                if intent == "read_events":
                    return f"{response}\n\n{action_result}"
                return response
            
            # For other cases, use local generation
            return self._local_generate_response(action_result, intent, entities)
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I've completed your request."

    def _local_generate_response(self, action_result: str, intent: str = None, 
                                  entities: dict = None) -> str:
        """Generate response locally without any API call. Bilingual & tone-aware."""
        name = self.user_name
        detected_language = self.detect_language(action_result) if action_result else "English"
        is_hindi = detected_language in ("Hindi", "Hinglish")
        
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