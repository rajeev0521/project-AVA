import os
from datetime import datetime
import re
from dotenv import load_dotenv
from tzlocal import get_localzone
from typing import Optional, Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

class CalendarIntent(BaseModel):
    intent: Optional[str] = Field(description="The intent of the user. One of: create_event, read_events, update_event, delete_event")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Extracted entities like title, start_time, end_time (in ISO 8601 with timezone), event_id, etc.")

class NLPProcessor:
    def __init__(self, user_name=None, language=None, tone=None):
        # Configure env
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        # Initialize LangChain model
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=api_key,
            temperature=0.0
        )
        
        # Structured output parser for intent
        self.intent_parser = self.llm.with_structured_output(CalendarIntent)
        
        # Get local timezone
        self.local_tz = get_localzone()
        # Load user config from environment variables
        self.user_name = user_name or os.getenv("AVA_USER_NAME", "sir")
        self.language = language or os.getenv("AVA_LANGUAGE", "English")
        self.tone = tone or os.getenv("AVA_TONE", "formal")

        # Load system prompt from file
        prompt_path = os.path.join(os.path.dirname(__file__), 'system_prompt.txt')
        with open(prompt_path, 'r') as f:
            self.system_prompt_template = f.read()

        # Define prompts
        self.intent_prompt = PromptTemplate.from_template(
            "{system_prompt}\n\nUser command: {command}"
        )
        
        self.response_prompt = PromptTemplate.from_template(
            "You are an AI assistant. Always start your response with a polite greeting using the user's name: '{user_name}'. "
            "Vary your phrasing for confirmations and use a {tone} tone. Respond in {language}.\n\n"
            "Action result: {action_result}\n"
            "Intent: {intent}\n"
            "Entities: {entities_json}\n\n"
            "If the action was to create an event, include the event title, date, and time in the response. "
            "If the action was to update or delete, mention the event and the action. "
            "If the action failed, provide a helpful error message. Do not include extra explanations or apologies unless there was an error."
        )

        
    def _get_system_prompt(self):
        """Formats the system prompt with dynamic data."""
        now = datetime.now(self.local_tz)
        return self.system_prompt_template.format(
            local_tz=str(self.local_tz),
            current_date_time=now.strftime('%Y-%m-%d %H:%M:%S %Z'),
            current_date=now.strftime('%Y-%m-%d')
        )

    def process_command(self, command):
        """Process natural language command using LangChain and extract intent and entities"""
        try:
            system_prompt = self._get_system_prompt()
            
            chain = self.intent_prompt | self.intent_parser
            result = chain.invoke({
                "system_prompt": system_prompt,
                "command": command
            })
            
            if not result or not result.intent:
                 return self._fallback_parsing(command)

            intent = result.intent
            entities = result.entities or {}

            # Validate and fix time formats
            entities = self._validate_and_fix_times(entities)

            print(f"Processed intent: {intent}")
            print(f"Processed entities: {entities}")

            return intent, entities

        except Exception as e:
            print(f"Error processing command with LangChain: {str(e)}")
            return self._fallback_parsing(command)

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
                    print(f"Error parsing time {time_str}: {e}")
                    # Keep original if parsing fails
                    
        return entities

    def _fallback_parsing(self, command):
        """Enhanced fallback parsing when LangChain extraction fails"""
        command_lower = command.lower()

        # Determine intent
        if any(word in command_lower for word in ['delete', 'cancel', 'remove']):
            intent = 'delete_event'
        elif any(word in command_lower for word in ['update', 'change', 'modify']):
            intent = 'update_event'
        elif any(word in command_lower for word in ['show', 'list', 'what', 'events']):
            intent = 'read_events'
        elif any(word in command_lower for word in ['schedule', 'create', 'add', 'book']):
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
            else:
                # Default times
                start_dt = datetime.combine(event_date, datetime.min.time().replace(hour=14, minute=0)).replace(tzinfo=self.local_tz)
                end_dt = datetime.combine(event_date, datetime.min.time().replace(hour=15, minute=0)).replace(tzinfo=self.local_tz)
                
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()

        return intent, entities

    def generate_response(self, action_result, intent=None, entities=None):
        """Generate a natural language response for the user using LangChain"""
        try:
            if intent and entities:
                import json
                # Format times for display
                display_entities = entities.copy()
                for time_key in ['start_time', 'end_time']:
                    if time_key in display_entities:
                        try:
                            dt = datetime.fromisoformat(str(display_entities[time_key]))
                            display_entities[time_key] = dt.strftime('%B %d, %Y at %I:%M %p')
                        except:
                            pass

                # Use a standard LLM call, not structured output, for generating dialogue
                llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=os.getenv('GEMINI_API_KEY'))
                chain = self.response_prompt | llm | StrOutputParser()
                response = chain.invoke({
                    "user_name": self.user_name,
                    "tone": self.tone,
                    "language": self.language,
                    "action_result": action_result,
                    "intent": intent,
                    "entities_json": json.dumps(display_entities)
                })
                return response.strip()
            
            # Fallback to static responses if no details are available or error
            if "created" in action_result.lower():
                return f"Okay {self.user_name}, I've successfully created your event."
            elif "error" in action_result.lower():
                return f"Okay {self.user_name}, there was an issue with your request. Please try again with a different time or date."
            elif "updated" in action_result.lower():
                return f"Okay {self.user_name}, I've updated your event."
            elif "deleted" in action_result.lower():
                return f"Okay {self.user_name}, I've deleted the event."
            elif "no upcoming events" in action_result.lower():
                return f"Okay {self.user_name}, you don't have any upcoming events."
            else:
                return action_result
        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return "I've completed your request." 