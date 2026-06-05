import os
import json
import google.generativeai as genai
from datetime import datetime

class NLTimeParser:
    """Parses natural language time expressions into structured ISO datetimes using Gemini."""
    
    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=(
                "Extract date and time from the natural language phrase. "
                "Respond ONLY with a JSON object in this exact format: "
                '{"start_time": "YYYY-MM-DDTHH:MM:SS", "end_time": "YYYY-MM-DDTHH:MM:SS"}. '
                "If end_time is not implied, set it to null."
            )
        )
        
    async def parse(self, text: str, current_time: datetime = None) -> dict:
        """Parses the text and returns a dictionary with start_time and end_time."""
        if not current_time:
            current_time = datetime.now()
            
        prompt = f"Current time is: {current_time.isoformat()}\nParse this phrase: '{text}'"
        
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)
        except Exception as e:
            return {"error": str(e)}
