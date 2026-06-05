import os
import google.generativeai as genai
from google.generativeai.types import content_types
from typing import Optional
from datetime import datetime
from ava.brain.tool_router import ToolRouter
from ava.conversation.state_manager import UserSession

class AssistantResponse:
    def __init__(self, text: str, action_taken: Optional[str] = None, requires_followup: bool = False):
        self.text = text
        self.action_taken = action_taken
        self.requires_followup = requires_followup

class AssistantBrain:
    """The central orchestrator using Gemini 2.0 Flash."""
    
    def __init__(self, tool_router: ToolRouter):
        self.tool_router = tool_router
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)
            
        # Initialize Gemini 2.0 Flash model
        tools_list = self.tool_router.get_all_tool_schemas()
        
        # If tools list is empty, we don't pass it to the model to avoid errors
        if tools_list:
            self.model = genai.GenerativeModel(
                model_name="gemini-2.0-flash",
                tools=tools_list
            )
        else:
            self.model = genai.GenerativeModel(model_name="gemini-2.0-flash")

    async def process(self, user_query: str, session: UserSession) -> AssistantResponse:
        """Processes a user query and returns a structured response."""
        
        # Load or start chat
        if not session.chat_session:
            session.chat_session = self.model.start_chat(enable_automatic_function_calling=False)
            
        chat = session.chat_session
        response = chat.send_message(user_query)
        
        # Update conversation state
        session.conversation_state.turn_count += 1
        session.conversation_state.updated_at = datetime.now()
        session.conversation_state.last_query = user_query
        
        action_taken = None
        
        # Check if the model wants to call a function
        if response.parts and hasattr(response.parts[0], 'function_call') and response.parts[0].function_call:
            fc = response.parts[0].function_call
            action_taken = fc.name
            
            # Extract arguments
            kwargs = {}
            if fc.args:
                for key, val in fc.args.items():
                    kwargs[key] = val
                
            # Execute the requested tool
            try:
                tool_result = await self.tool_router.execute_tool(fc.name, kwargs)
                
                # Format result for the model
                function_response = {"result": tool_result}
                
                # Send result back to the model to get the final natural language answer
                response = chat.send_message(
                    content_types.Part.from_function_response(
                        name=fc.name,
                        response=function_response
                    )
                )
            except Exception as e:
                # Send error back to the model
                response = chat.send_message(
                    content_types.Part.from_function_response(
                        name=fc.name,
                        response={"error": str(e)}
                    )
                )
                
        return AssistantResponse(
            text=response.text,
            action_taken=action_taken,
            requires_followup=False  # Simplified for Phase 1
        )
