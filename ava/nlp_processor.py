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
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Tuple

from .logger import get_logger
from .config import config

try:
    from .intent_classifier import IntentClassifier
    from .entity_extractor import EntityExtractor
except ImportError:
    IntentClassifier = None
    EntityExtractor = None

logger = get_logger(__name__)

class CalendarEntities(BaseModel):
    """Structured entities for calendar actions."""
    title: Optional[str] = Field(default=None, description="The title of the event.")
    start_time: Optional[str] = Field(default=None, description="Start date/time in ISO 8601 format.")
    end_time: Optional[str] = Field(default=None, description="End date/time in ISO 8601 format.")
    location: Optional[str] = Field(default=None, description="Location of the event.")
    description: Optional[str] = Field(default=None, description="Description of the event.")
    event_id: Optional[str] = Field(default=None, description="The specific calendar event ID.")
    event_ids: Optional[list[str]] = Field(default=None, description="List of calendar event IDs for bulk operations.")
    date: Optional[str] = Field(default=None, description="General date reference (e.g. today, tomorrow, specific date).")

class CalendarIntent(BaseModel):
    """Structured output schema for Gemini intent extraction."""
    intent: Optional[str] = Field(
        description="The intent of the user. One of: create_event, read_events, update_event, delete_event, general_conversation"
    )
    entities: Optional[CalendarEntities] = Field(
        default_factory=CalendarEntities,
        description="Extracted entities like title, start_time, end_time, event_id, etc."
    )
    response_template: str = Field(
        default="",
        description="For calendar actions, a brief confirmation. For general_conversation, provide the complete helpful answer to the user's query here."
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
    def __init__(self):
        """
        Initialize a stateless NLP Processor.
        Thread-safe: context (user_name, timezone, memory) is passed per-request.
        """
        self.client = genai.Client(api_key=config.gemini_api_key)
        
        # Load system prompt from file
        prompt_path = os.path.join(os.path.dirname(__file__), 'system_prompt.txt')
        with open(prompt_path, 'r') as f:
            self.system_prompt_template = f.read()

        # Local intent classifier (lazy loaded)
        self._intent_classifier = None
        
        logger.info("Stateless NLPProcessor initialized (model=gemini-2.0-flash)")

    def _get_local_tz(self, timezone_str: str):
        """Convert string timezone to pytz object."""
        if timezone_str:
            import pytz
            try:
                return pytz.timezone(timezone_str)
            except pytz.UnknownTimeZoneError:
                pass
        from tzlocal import get_localzone
        return get_localzone()
    
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
        """Check if the command is purely a greeting."""
        import re
        cmd_lower = re.sub(r'[^\w\s]', '', command.lower()).strip()
        
        # Strip common wake words and names
        cmd_lower = re.sub(r'\b(ava|hey|hi|hello)\b', '', cmd_lower).strip()
        
        # If empty after removing name/greetings, it was just a greeting
        if not cmd_lower:
            return True
            
        # Or if the remaining text is exactly one of the greeting patterns
        return cmd_lower in _GREETING_PATTERNS
    
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
        
    def _get_system_prompt(self, local_tz):
        """Formats the system prompt with dynamic data."""
        now = datetime.now(local_tz)
        prompt = self.system_prompt_template
        prompt = prompt.replace("{local_tz}", str(local_tz))
        prompt = prompt.replace("{current_date_time}", now.strftime('%Y-%m-%d %H:%M:%S %Z'))
        prompt = prompt.replace("{current_date}", now.strftime('%Y-%m-%d'))
        return prompt

    def _get_conversation_history(self, memory) -> str:
        """Get formatted conversation history from memory manager."""
        if memory:
            try:
                return memory.get_context_prompt()
            except Exception as e:
                logger.warning(f"Failed to get conversation history: {e}")
        return "No previous conversation."

    def process_command(self, command: str, user_name: str, timezone_str: str, memory) -> Tuple[Optional[str], Dict[str, Any], str]:
        """
        Process natural language command. Returns (intent, entities, response_template).
        
        Handles greetings and off-topic queries before NLP processing.
        Uses two-tier approach for calendar commands:
        1. Local classifier (fast, ~5ms) if confidence >= 0.80
        2. Gemini API full extraction (slower, ~1-3s) for uncertain commands
        """
        user_name = sanitize_user_input(user_name) if user_name else "there"
        local_tz = self._get_local_tz(timezone_str)

        # Pre-filter: handle pure greetings locally without NLP processing
        if self.is_greeting(command):
            detected_lang = self.detect_language(command)
            if detected_lang in ("Hindi", "Hinglish"):
                greeting = f"Namaste {user_name}! Main AVA hoon, aapki AI assistant. Main aapke calendar ko manage kar sakti hoon aur general sawalo ke jawab bhi de sakti hoon."
            else:
                greeting = f"Hi {user_name}! I'm AVA, your AI assistant. I can help manage your calendar, or answer any general questions you have. How can I help today?"
            return None, {}, greeting

        # Step 1: Detect language from user's input
        detected_language = self.detect_language(command)
        logger.info(f"Detected language: {detected_language}")

        # Step 2: Resolve references if memory is available
        resolved_command = command
        if memory:
            try:
                resolved_command = memory.resolve_reference(command)
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
                    # Instantiate EntityExtractor explicitly with the local_tz
                    extractor = EntityExtractor(local_tz) if EntityExtractor is not None else None
                    if extractor is not None:
                        entities = extractor.extract(resolved_command, intent)
                    else:
                        entities = {}
                    
                    # Check if we have enough entities to execute
                    if self._can_execute_with_entities(intent, entities):
                        response_template = self._local_response_template(intent, entities, user_name, detected_language)
                        logger.info("Full local resolution — no API call")
                        return intent, entities, response_template
                    else:
                        # Partial local: we know the intent, ask Gemini only for entities
                        logger.info(f"Intent local ({confidence:.2f}), sending to Gemini for entity extraction only")
                        return self._gemini_extract_entities_only(resolved_command, intent, detected_language, dynamic_tone, user_name, local_tz, memory)
            except Exception as e:
                logger.warning(f"Local classifier error: {e}")

        # Tier 2: Fall back to Gemini API for full extraction
        return self._gemini_extract(resolved_command, detected_language, user_name, local_tz, memory)

    def _gemini_extract(self, command: str, detected_language: str, user_name: str, local_tz, memory) -> Tuple[Optional[str], Dict[str, Any], str]:
        """Extract intent and entities using Gemini API."""
        try:
            system_prompt = self._get_system_prompt(local_tz)
            conversation_history = self._get_conversation_history(memory)
            dynamic_tone = "friendly"
            
            prompt_text = (
                f"{system_prompt}\n\n"
                f"## Conversation History (most recent):\n{conversation_history}\n\n"
                f"## Response Settings:\n"
                f"- Respond in: {detected_language}\n"
                f"- Tone: {dynamic_tone}\n"
                f"- User's name: {user_name}\n\n"
                f"User command: {command}"
            )
            
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CalendarIntent,
                    temperature=0.0,
                ),
            )
            
            if not response.text:
                logger.warning(f"Gemini returned empty response for: {command}")
                return self._fallback_parsing(command, detected_language, local_tz)
            
            # Parse the JSON response into our model
            try:
                import json
                result = CalendarIntent.model_validate_json(response.text)
            except Exception as e:
                logger.error(f"Failed to parse Gemini JSON: {e}")
                return self._fallback_parsing(command, detected_language, local_tz)

            if not result.intent:
                logger.warning(f"Gemini returned no intent for: {command}")
                return self._fallback_parsing(command, detected_language, local_tz)

            intent = result.intent
            entities = result.entities.model_dump(exclude_none=True) if result.entities else {}
            response_template = result.response_template or ""
            
            # Set dynamic tone based on the extracted intent
            dynamic_tone = self.get_dynamic_tone(intent)

            # Validate and fix time formats
            entities = self._validate_and_fix_times(entities, local_tz)

            logger.info(f"Gemini extracted: intent={intent}, entities={list(entities.keys())}")
            return intent, entities, response_template

        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            intent, entities, _ = self._fallback_parsing(command, detected_language, local_tz)
            response_template = self._local_response_template(intent, entities, user_name, detected_language) if intent else ""
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
        self, command: str, local_intent: str, detected_language: str, dynamic_tone: str, user_name: str, local_tz, memory
    ) -> Tuple[Optional[str], Dict[str, Any], str]:
        """
        Use Gemini only for entity extraction, preserving the locally classified intent.
        """
        try:
            system_prompt = self._get_system_prompt(local_tz)
            conversation_history = self._get_conversation_history(memory)
            
            prompt_text = (
                f"{system_prompt}\n\n"
                f"## Conversation History (most recent):\n{conversation_history}\n\n"
                f"## Response Settings:\n"
                f"- Respond in: {detected_language}\n"
                f"- Tone: {dynamic_tone}\n"
                f"- User's name: {user_name}\n\n"
                f"User command: {command}"
            )
            
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CalendarIntent,
                    temperature=0.0,
                ),
            )
            
            result = None
            if response.text:
                try:
                    import json
                    result = CalendarIntent.model_validate_json(response.text)
                except Exception as e:
                    logger.error(f"Failed to parse Gemini JSON: {e}")
            
            if result and result.entities:
                entities_dict = result.entities.model_dump(exclude_none=True) if hasattr(result.entities, 'model_dump') else result.entities.dict(exclude_none=True)
                entities = self._validate_and_fix_times(entities_dict, local_tz)
            else:
                entities = {}
            
            response_template = result.response_template if result else ""
            
            logger.info(f"Gemini entity extraction: intent={local_intent} (local), entities={list(entities.keys())}")
            return local_intent, entities, response_template or ""
            
        except Exception as e:
            logger.error(f"Gemini entity extraction failed: {e}")
            # Fall back to whatever entities the local extractor got
            extractor = EntityExtractor(local_tz) if EntityExtractor is not None else None
            if extractor is not None:
                entities = extractor.extract(command, local_intent)
            else:
                entities = {}
            response_template = self._local_response_template(local_intent, entities, user_name, detected_language)
            return local_intent, entities, response_template

    def _local_response_template(self, intent: Optional[str], entities: Dict[str, Any], user_name: str, detected_language: str = "English") -> str:
        """Generate a response template locally without API call. Language-aware."""
        if not intent:
            if detected_language in ("Hindi", "Hinglish"):
                return "Maaf kijiye, aapka request samajh nahi aaya."
            return "I couldn't understand your request."
        
        title = entities.get('title', 'your event')
        name = user_name
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

    def _validate_and_fix_times(self, entities, local_tz):
        """Validate and fix time formats to ensure they're in local timezone"""
        for time_key in ['start_time', 'end_time']:
            if time_key in entities:
                time_str = entities[time_key]
                if not isinstance(time_str, str):
                    continue
                try:
                    # Remove timezone offset/Z to get naive time
                    if 'Z' in time_str:
                        time_str = time_str.replace('Z', '')
                    elif '+' in time_str and len(time_str) > 19:
                        time_str = time_str[:19]
                    elif '-' in time_str and len(time_str) > 19 and time_str.rfind('-') > 10:
                        time_str = time_str[:19]
                        
                    dt = datetime.fromisoformat(time_str)
                    
                    # Apply the user's correct local timezone
                    if hasattr(local_tz, 'localize'):
                        dt = local_tz.localize(dt)
                    else:
                        dt = dt.replace(tzinfo=local_tz)
                    
                    # Convert back to ISO format with local timezone
                    entities[time_key] = dt.isoformat()
                    
                except ValueError as e:
                    logger.warning(f"Error parsing time {time_str}: {e}")
                    # Keep original if parsing fails
                    
        return entities

    def _fallback_parsing(self, command, detected_language: str, local_tz):
        """Enhanced fallback parsing when Gemini extraction fails, using EntityExtractor."""
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
            return None, {}, ""

        extractor = EntityExtractor(local_tz) if EntityExtractor is not None else None
        if extractor is not None:
            entities = extractor.extract(command, intent)
        else:
            entities = {}
            if intent == 'create_event':
                entities['title'] = 'Event'
                # Default times
                event_date = datetime.now(local_tz).date()
                start_dt = datetime.combine(event_date, datetime.min.time().replace(hour=14, minute=0)).replace(tzinfo=local_tz)
                end_dt = datetime.combine(event_date, datetime.min.time().replace(hour=15, minute=0)).replace(tzinfo=local_tz)
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()

        return intent, entities, ""

    def generate_response(self, intent: str, entities: dict, action_result: str, response_template: str, user_name: str, timezone_str: str, memory) -> str:
        """
        Generate a natural language response for the user.
        
        IMPORTANT: Never prepends a positive template when the action_result
        signals empty results, errors, or auth requirements.
        """
        user_name = sanitize_user_input(user_name) if user_name else "there"
        
        try:
            # Guard: detect negative/error/auth conditions in action_result
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
                response = response_template.replace("{user_name}", user_name)
                logger.info("Using pre-generated response template (no API call)")
                if intent == "read_events":
                    return f"{response}\n\n{action_result}"
                return response
            
            # For other cases, use local generation
            return self._local_generate_response(action_result, intent, entities, user_name)
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I've completed your request."

    def _local_generate_response(self, action_result: str, intent: str, 
                                  entities: dict, user_name: str) -> str:
        """Generate response locally without any API call. Bilingual & tone-aware."""
        name = user_name
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