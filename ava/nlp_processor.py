import os
import google.generativeai as genai
from datetime import datetime, timedelta
import json
import re
from dotenv import load_dotenv
from tzlocal import get_localzone
import pytz

class NLPProcessor:
    def __init__(self, user_name=None, language=None, tone=None):
        # Configure Gemini API
        load_dotenv()
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-pro-latest')
        
        # Get local timezone
        self.local_tz = get_localzone()
        # Load user config from environment variables, with defaults
        self.user_name = user_name or os.getenv("AVA_USER_NAME", "sir")
        self.language = language or os.getenv("AVA_LANGUAGE", "English")
        self.tone = tone or os.getenv("AVA_TONE", "formal")

        # System prompt to guide Gemini's responses
        self.system_prompt = f"""
You are an intelligent calendar assistant. Your job is to extract structured information from user commands related to calendar events.

IMPORTANT: The user is in the timezone: {str(self.local_tz)}
Current date and time: {datetime.now(self.local_tz).strftime('%Y-%m-%d %H:%M:%S %Z')}

For every input command, follow these steps:

1. **Determine the intent**, which must be one of the following:
   - "create_event"
   - "read_events"
   - "update_event"
   - "delete_event"

2. **Extract relevant entities** (if present), which can include:
   - "title": The name or purpose of the event (e.g., "Doctor Appointment")
   - "start_time": The event start time in **ISO 8601 format with numeric timezone offset** (e.g., "2025-06-25T14:00:00+05:45")
   - "end_time": The event end time in **ISO 8601 format with numeric timezone offset** (e.g., "2025-06-25T15:00:00+05:45")
   - "event_id": The unique ID of the event (used in update or delete)

3. **ALWAYS return the output as a valid JSON object**, matching the following schema:

Example:
{{
  "intent": "create_event",
  "entities": {{
    "title": "Team Meeting",
    "start_time": "2025-06-25T14:00:00+05:45",
    "end_time": "2025-06-25T15:00:00+05:45"
  }}
}}

CRITICAL TIME CONVERSION RULES:
- When user says "2:00 p.m." or "2 PM", convert to 14:00 in 24-hour format
- When user says "3:00 p.m." or "3 PM", convert to 15:00 in 24-hour format
- Always use the user's local timezone: {str(self.local_tz)}
- If no date is specified, assume today's date: {datetime.now(self.local_tz).strftime('%Y-%m-%d')}
- If user mentions a specific date like "25th June 2025", use that exact date: 2025-06-25
- **Do NOT use zone names like 'Asia/Katmandu'. Always use the numeric offset (e.g., '+05:45').**

If the command is ambiguous or unrecognizable, return:
{{
  "intent": null,
  "entities": {{}}
}}

The response must be **valid JSON only** without explanations or extra text
"""

    def process_command(self, command):
        """Process natural language command using Gemini and extract intent and entities"""
        try:
            prompt = f"{self.system_prompt}\n\nUser command: {command}\n\nPlease respond with only the JSON structure, no additional text."
            response = self.model.generate_content(prompt)

            # Clean the response text - remove any markdown formatting
            response_text = response.text.strip()
            if response_text.startswith('```'):
                response_text = re.sub(r"^```[a-zA-Z]*\n?", "", response_text)
                response_text = re.sub(r"```$", "", response_text)
                response_text = response_text.strip()
            response_text = re.sub(r'//.*', '', response_text)

            try:
                result = json.loads(response_text)
                intent = result.get('intent')
                entities = result.get('entities', {})

                # Validate and fix time formats
                entities = self._validate_and_fix_times(entities)

                print(f"Processed intent: {intent}")
                print(f"Processed entities: {entities}")

                return intent, entities

            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                print(f"Response text: {response_text}")
                return self._fallback_parsing(command)

        except Exception as e:
            print(f"Error processing command with Gemini: {str(e)}")
            return self._fallback_parsing(command)

    def _validate_and_fix_times(self, entities):
        """Validate and fix time formats to ensure they're in local timezone"""
        for time_key in ['start_time', 'end_time']:
            if time_key in entities:
                time_str = entities[time_key]
                
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
                            dt = self.local_tz.localize(dt)
                    
                    # Convert back to ISO format with local timezone
                    entities[time_key] = dt.isoformat()
                    
                except ValueError as e:
                    print(f"Error parsing time {time_str}: {e}")
                    # Keep original if parsing fails
                    
        return entities

    def _fallback_parsing(self, command):
        """Enhanced fallback parsing when Gemini fails"""
        command_lower = command.lower()

        # Determine intent
        if any(word in command_lower for word in ['schedule', 'create', 'add', 'book', 'meeting']):
            intent = 'create_event'
        elif any(word in command_lower for word in ['show', 'list', 'what', 'events']):
            intent = 'read_events'
        elif any(word in command_lower for word in ['update', 'change', 'modify']):
            intent = 'update_event'
        elif any(word in command_lower for word in ['delete', 'cancel', 'remove']):
            intent = 'delete_event'
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
                r'(\d{1,2}):?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.)',
                r'(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)'
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
            current_year = datetime.now().year
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
                
                start_dt = self.local_tz.localize(datetime.combine(event_date, datetime.min.time().replace(hour=start_hour, minute=start_minute)))
                end_dt = self.local_tz.localize(datetime.combine(event_date, datetime.min.time().replace(hour=end_hour, minute=end_minute)))
                
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()
            else:
                # Default times
                start_dt = self.local_tz.localize(datetime.combine(event_date, datetime.min.time().replace(hour=14, minute=0)))
                end_dt = self.local_tz.localize(datetime.combine(event_date, datetime.min.time().replace(hour=15, minute=0)))
                
                entities['start_time'] = start_dt.isoformat()
                entities['end_time'] = end_dt.isoformat()

        return intent, entities

    def generate_response(self, action_result, intent=None, entities=None):
        """Generate a natural language response for the user using Gemini"""
        try:
            if intent and entities:
                # Format times for display
                display_entities = entities.copy()
                for time_key in ['start_time', 'end_time']:
                    if time_key in display_entities:
                        try:
                            dt = datetime.fromisoformat(display_entities[time_key])
                            display_entities[time_key] = dt.strftime('%B %d, %Y at %I:%M %p')
                        except:
                            pass

                prompt = f"""
You are an AI assistant. Always start your response with a polite greeting using the user's name: '{self.user_name}'. Vary your phrasing for confirmations and use a {self.tone} tone. Respond in {self.language}.

Action result: {action_result}
Intent: {intent}
Entities: {json.dumps(display_entities)}

If the action was to create an event, include the event title, date, and time in the response. If the action was to update or delete, mention the event and the action. If the action failed, provide a helpful error message. Do not include extra explanations or apologies unless there was an error.
"""
                response = self.model.generate_content(prompt)
                return response.text.strip()
            # Fallback to static responses if no details are available
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