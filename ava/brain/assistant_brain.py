import json
import os
import re
import google.generativeai as genai
# Removed deprecated content_types import
from typing import Optional
import asyncio
from datetime import datetime
from ava.brain.tool_router import ToolRouter
from ava.conversation.state_manager import UserSession
from ava.memory.short_term_memory import ShortTermMemory
from ava.memory.long_term_memory import LongTermMemory

class AssistantResponse:
    def __init__(self, text: str, action_taken: Optional[str] = None, requires_followup: bool = False):
        self.text = text
        self.action_taken = action_taken
        self.requires_followup = requires_followup

class AssistantBrain:
    """The central orchestrator using Gemini 2.0 Flash."""
    
    def __init__(self, tool_router: ToolRouter, short_term_memory: Optional[ShortTermMemory] = None, long_term_memory: Optional[LongTermMemory] = None):
        self.tool_router = tool_router
        self.short_term_memory = short_term_memory
        self.long_term_memory = long_term_memory
        from ava.config import config
        api_key = config.gemini_api_key
        if api_key and api_key != "missing":
            genai.configure(api_key=api_key)
            
        # Initialize Gemini 2.0 Flash model
        tools_list = self.tool_router.get_all_tool_schemas()
        
        # If tools list is empty, we don't pass it to the model to avoid errors
        if tools_list:
            self.model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                tools=tools_list
            )
        else:
            self.model = genai.GenerativeModel(model_name="gemini-2.5-flash")

    async def process(self, user_query: str, session: UserSession) -> AssistantResponse:
        """Processes a user query and returns a structured response."""
        
        # Load or start chat
        if not session.chat_session:
            session.chat_session = self.model.start_chat(enable_automatic_function_calling=False)
            
        chat = session.chat_session
        
        # Intent-gated preference retrieval
        context_prefix = ""
        if self.long_term_memory:
            scheduling_keywords = ["schedule", "book", "meeting", "event", "calendar", "move", "cancel", "update", "reschedule", "free", "time", "duration", "appointment"]
            if any(kw in user_query.lower() for kw in scheduling_keywords):
                prefs = self.long_term_memory.search_preferences(session.user_id, user_query)
                if prefs:
                    context_prefix = "User preferences relevant to this request:\n" + "\n".join(f"- {p.content}" for p in prefs) + "\n\n"
        
        augmented_query = context_prefix + user_query
        response = chat.send_message(augmented_query)
        
        # Update conversation state
        state = session.conversation_state
        state.turn_count += 1
        state.updated_at = datetime.now()
        state.last_query = user_query

        # Phase 4: Track conversation history
        state.add_turn("user", user_query)
        
        action_taken = None
        
        # Check if the model wants to call a function
        while response.parts and hasattr(response.parts[0], 'function_call') and response.parts[0].function_call:
            fc = response.parts[0].function_call
            action_taken = fc.name
            
            # Extract arguments
            kwargs = {}
            if fc.args:
                for key, val in fc.args.items():
                    kwargs[key] = val

            # Phase 4: Inject conversation state into resolve/find tools
            # so they can access last_event and conversation history
            self._inject_conversation_state(fc.name, session)
                
            # Execute the requested tool
            try:
                tool_result = await self.tool_router.execute_tool(fc.name, session, kwargs)
                
                # Phase 4: Auto-track events from tool results
                self._track_event_from_result(fc.name, tool_result, session)
                
                # Format result for the model
                function_response = {"result": tool_result}
                
                # Send result back to the model to get the final natural language answer
                response = chat.send_message(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name,
                            response=function_response
                        )
                    )
                )
            except Exception as e:
                # Send error back to the model
                response = chat.send_message(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fc.name,
                            response={"error": str(e)}
                        )
                    )
                )

        # Phase 4: Track assistant response in conversation history
        response_text = response.text
        
        state.add_turn("assistant", response_text, {"action": action_taken})
        
        # Phase 6: Async state persistence
        if self.short_term_memory:
            asyncio.create_task(self.short_term_memory.save_state(session.user_id, state))
                
        return AssistantResponse(
            text=response_text,
            action_taken=action_taken,
            requires_followup=False  # Simplified for Phase 1
        )

    def _inject_conversation_state(self, tool_name: str, session: UserSession) -> None:
        """
        Inject the current conversation state into tools that need it
        (resolve_calendar_event, find_calendar_event, memory tools) so they can
        access last_event, conversation history, and user context.
        """
        tool = self.tool_router.get_tool(tool_name)
        if tool:
            tool._conversation_state = session.conversation_state

    def _track_event_from_result(
        self, tool_name: str, result: any, session: UserSession
    ) -> None:
        """
        After a calendar tool call, extract event data from the result
        and update session.conversation_state.last_event.

        This enables pronoun resolution in subsequent turns:
        e.g., "Read today's events" → user sees events →
              "Delete it" → resolves to last mentioned event.
        """
        if not result:
            return

        # Handle resolve/find tool results (structured dicts)
        if isinstance(result, dict):
            if result.get("resolved") and result.get("event_id"):
                session.update_last_event(result)
                return

            if result.get("found") and result.get("events"):
                events = result["events"]
                if events:
                    # Track the top result
                    session.update_last_event(events[0])
                return

        # Handle string results from CRUD operations
        # If it's a create/update success message, we can't extract structured data,
        # but the event context is already in the conversation via the LLM.
        # The resolve tool will handle this via contextual resolution.
