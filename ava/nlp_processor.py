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

Important: Always format dates and times in ISO format (YYYY-MM-DDTHH:MM:SS) and assume the current year if not specified.
Example:
{
  "intent": "create_event",
  "entities": {
    "title": "Team Meeting",
    "start_time": "2025-07-10T14:00:00",
    "end_time": "2025-07-10T15:00:00"
  }
}

If the command is ambiguous or unrecognizable, return:
{
  "intent": null,
  "entities": {}
}
"""
    
    def process_command(self, command):
        """Process natural language command using Gemini and extract intent and entities"""
        try:
            # Create the prompt for Gemini
            prompt = f"{self.system_prompt}\n\nUser command: {command}\n\nPlease respond with only the JSON structure, no additional text."
            
            # Get response from Gemini
            response = self.model.generate_content(prompt)
            print(f"Gemini response: {response.text}")

            # Clean the response text - remove any markdown formatting
            response_text = response.text.strip()
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            # Now try parsing
            try:
                # Convert the response text to a dictionary
                result = json.loads(response_text)
                intent = result.get('intent')
                entities = result.get('entities', {})
                
                def _parse_iso8601(dt_str):
                    if dt_str.endswith('Z'):
                        dt_str = dt_str[:-1] + '+00:00'
                    return datetime.fromisoformat(dt_str)

                if 'start_time' in entities and isinstance(entities['start_time'], str) and entities['start_time']:
                    entities['start_time'] = _parse_iso8601(entities['start_time'])
                if 'end_time' in entities and isinstance(entities['end_time'], str) and entities['end_time']:
                    entities['end_time'] = _parse_iso8601(entities['end_time'])
                
                return intent, entities
                
            except json.JSONDecodeError as e:
                print(f"Error parsing Gemini response: {e}")
                print("Cleaned response was:\n", cleaned)
                intent, entities = None, {}
                
        except Exception as e:
            print(f"Error processing command with Gemini: {str(e)}")
            return None, {}
    
    def generate_response(self, action_result):
        """Generate a natural language response for the user"""
        try:
            prompt = f"""Generate a natural, conversational response for the following calendar action result:
            {action_result}
            
            The response should be friendly and concise."""
            
            response = self.model.generate_content(prompt)
            return response.text
            
        except Exception as e:
            print(f"Error generating response with Gemini: {str(e)}")
            return "I'm sorry, I couldn't generate a proper response." 