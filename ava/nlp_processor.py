import os
import google.generativeai as genai
from datetime import datetime, timedelta
import json
import re

class NLPProcessor:
    def __init__(self):
        # Configure Gemini API
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-pro-latest')

        # System prompt to guide Gemini's responses
        self.system_prompt = """
You are an intelligent calendar assistant. Your job is to extract structured information from user commands related to calendar events.

For every input command, follow these steps:

1. **Determine the intent**, which must be one of the following:
   - "create_event"
   - "read_events"
   - "update_event"
   - "delete_event"

2. **Extract relevant entities** (if present), which can include:
   - "title": The name or purpose of the event (e.g., "Doctor Appointment")
   - "start_time": The event start time in **ISO 8601 format** (e.g., "2025-07-10T14:00:00Z")
   - "end_time": The event end time in **ISO 8601 format** (e.g., "2025-07-10T15:00:00Z")
   - "event_id": The unique ID of the event (used in update or delete)

3. **ALWAYS return the output as a valid JSON object**, matching the following schema:

Example:
{
  "intent": "create_event",
  "entities": {
    "title": "Team Meeting",
    "start_time": "2025-07-10T14:00:00Z",
    "end_time": "2025-07-10T15:00:00Z"
  }
}

If the command is ambiguous or unrecognizable, return:
{
  "intent": null,
  "entities": {}
}

Constraints:
- Use "Z" suffix for UTC time or use full ISO 8601 with timezone offset (e.g., "+05:45")
- If the user provides a date or time in natural language (e.g., "2:00 p.m." or "next Friday"), convert it to ISO 8601 format if possible.
- The response must be **valid JSON only** without explanations or extra text
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

                # Ensure times are strings if present
                if 'start_time' in entities and not isinstance(entities['start_time'], str):
                    entities['start_time'] = str(entities['start_time'])
                if 'end_time' in entities and not isinstance(entities['end_time'], str):
                    entities['end_time'] = str(entities['end_time'])

                return intent, entities

            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                print(f"Response text: {response_text}")
                return self._fallback_parsing(command)

        except Exception as e:
            print(f"Error processing command with Gemini: {str(e)}")
            return self._fallback_parsing(command)

    def _fallback_parsing(self, command):
        """Simple fallback parsing when Gemini fails"""
        command_lower = command.lower()

        # Determine intent
        if any(word in command_lower for word in ['schedule', 'create', 'add', 'book']):
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
            # Try to extract title (very basic)
            if 'meeting' in command_lower:
                entities['title'] = 'Meeting'
            elif 'appointment' in command_lower:
                entities['title'] = 'Appointment'
            else:
                entities['title'] = 'Event'

            # For now, set default times (you can make this more sophisticated)
            today = datetime.now()
            entities['start_time'] = today.replace(minute=0, second=0, microsecond=0).isoformat()
            entities['end_time'] = (today + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat()

        return intent, entities

    def generate_response(self, action_result, intent=None, entities=None):
        """Generate a natural language response for the user using Gemini"""
        try:
            # If intent and entities are provided, use them to generate a dynamic response
            if intent and entities:
                prompt = f"""
You are an AI assistant. Write a friendly, concise, and natural-sounding confirmation message for a calendar action.

Action result: {action_result}
Intent: {intent}
Entities: {json.dumps(entities)}

If the action was to create an event, include the event title, date, and time in the response. If the action was to update or delete, mention the event and the action. If the action failed, provide a helpful error message. Do not include extra explanations or apologies unless there was an error.
"""
                response = self.model.generate_content(prompt)
                return response.text.strip()
            # Fallback to static responses if no details are available
            if "created" in action_result.lower():
                return "Great! I've successfully created your event."
            elif "error" in action_result.lower():
                return "I'm sorry, there was an issue with your request. Please try again with a different time or date."
            elif "updated" in action_result.lower():
                return "Perfect! I've updated your event."
            elif "deleted" in action_result.lower():
                return "Done! I've deleted the event."
            elif "no upcoming events" in action_result.lower():
                return "You don't have any upcoming events."
            else:
                return action_result
        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return "I've completed your request." 