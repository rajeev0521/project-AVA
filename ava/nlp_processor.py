import os
import google.generativeai as genai
from datetime import datetime, timedelta

class NLPProcessor:
    def __init__(self):
        # Configure Gemini API
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-pro-latest')
        
        # System prompt to guide Gemini's responses
        self.system_prompt = """You are an AI assistant that helps process calendar-related commands. 
        For any given command, you should:
        1. Determine the intent (create_event, read_events, update_event, delete_event)
        2. Extract relevant entities (title, start_time, end_time, event_id)
        3. Return the response in a structured format
        
        Example response format:
        {
            "intent": "create_event",
            "entities": {
                "title": "Team Meeting",
                "start_time": "2024-03-20T10:00:00",
                "end_time": "2024-03-20T11:00:00"
            }
        }
        
        If the command is unclear or cannot be processed, return:
        {
            "intent": null,
            "entities": {}
        }"""
    
    def process_command(self, command):
        """Process natural language command using Gemini and extract intent and entities"""
        try:
            # Create the prompt for Gemini
            prompt = f"{self.system_prompt}\n\nUser command: {command}"
            
            # Get response from Gemini
            response = self.model.generate_content(prompt)
            
            # Parse the response
            # Note: In a production environment, you'd want to add more robust parsing
            # and error handling here
            try:
                # Convert the response text to a dictionary
                import json
                result = json.loads(response.text)
                
                intent = result.get('intent')
                entities = result.get('entities', {})
                
                # Convert string timestamps to datetime objects if present
                if 'start_time' in entities:
                    entities['start_time'] = datetime.fromisoformat(entities['start_time'])
                if 'end_time' in entities:
                    entities['end_time'] = datetime.fromisoformat(entities['end_time'])
                
                return intent, entities
                
            except json.JSONDecodeError:
                print("Error parsing Gemini response:", response.text)
                return None, {}
                
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