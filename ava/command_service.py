"""
Command Service for AVA.
Provides a unified pipeline for processing natural language calendar commands,
used by both REST and WebSocket endpoints. Eliminates code duplication.
"""

import asyncio
from typing import Dict, Any

from pydantic import BaseModel

from .logger import get_logger
from .session_manager import UserSession
from .nlp_processor import NLPProcessor

logger = get_logger(__name__)


class CommandResult(BaseModel):
    """Result of processing a command."""
    intent: str | None = None
    entities: Dict[str, Any] = {}
    action_result: str = ""
    response: str = ""
    used_local_classifier: bool = False


class CommandService:
    """
    Unified pipeline for executing voice/text commands.
    Orchestrates NLP, Calendar API, and Memory.
    """
    
    def __init__(self, nlp_processor: NLPProcessor):
        """
        Initialize the command service.
        
        Args:
            nlp_processor: A shared NLPProcessor instance (stateless except for LLM client).
        """
        self.nlp = nlp_processor

    async def process_command(self, text: str, user_name: str, timezone_str: str, session: UserSession) -> CommandResult:
        """
        Process a single command from a user.
        
        Args:
            text: The user's command text.
            user_name: User's display name.
            timezone_str: User's local timezone (e.g. 'Asia/Kolkata').
            session: The user's active session containing calendar and memory managers.
            
        Returns:
            CommandResult containing intent, entities, and formatted response.
        """
        # 1. Check for pending confirmations (e.g., bulk delete)
        if session.awaiting_confirmation:
            return await self._handle_confirmation(text, session)
        
        # 2. Extract Intent and Entities
        # This is CPU/Network bound, so run it in a thread pool
        intent, entities, response_template = await asyncio.to_thread(
            self.nlp.process_command, text, user_name, timezone_str, session.memory_manager
        )
        
        # Track if we used local classifier vs Gemini (for analytics/UI)
        used_local = intent is not None and bool(self.nlp.intent_classifier)
        
        if not intent:
            # Handle greetings/off-topic/unknowns which return (None, {}, greeting_message)
            return CommandResult(
                intent=None,
                entities={},
                action_result="",
                response=response_template or "I'm sorry, I couldn't understand that.",
                used_local_classifier=used_local
            )
        
        if intent == "general_conversation":
            # A generic question answered by Gemini
            return CommandResult(
                intent=intent,
                entities=entities,
                action_result="",
                response=response_template,
                used_local_classifier=used_local
            )
        
        # 3. Execute Calendar Operation
        # Calendar API calls are blocking, must run in thread pool
        calendar_mgr = session.calendar_manager
        if not calendar_mgr:
            action_result = "Please sign in with Google using the button above before managing your calendar."
        else:
            action_result = await asyncio.to_thread(
                calendar_mgr.execute_command, intent, entities
            )
        
        # 4. Handle bulk delete confirmation flow
        if (
            intent == "delete_event" and 
            "Please confirm if you want to delete all these events" in action_result
        ):
            # Calendar manager stores the queried event IDs internally.
            # Retrieve them and save in session for the confirmed handler.
            event_ids = calendar_mgr.get_pending_delete_event_ids() if calendar_mgr else None
            
            session.awaiting_confirmation = True
            session.pending_action = "delete_events"
            session.pending_data = {
                **entities,
                "event_ids": event_ids or [],
            }
            
            # Return the confirmation prompt directly as both action_result and response
            return CommandResult(
                intent=intent,
                entities=entities,
                action_result=action_result,
                response=action_result,
                used_local_classifier=used_local
            )
        
        # 6. Generate Response
        response = await asyncio.to_thread(
            self.nlp.generate_response, intent, entities, action_result, response_template, user_name, timezone_str, session.memory_manager
        )
        
        # 6. Update Memory (History & Context)
        if session.memory_manager:
            try:
                # Add to conversation history
                await asyncio.to_thread(
                    session.memory_manager.add_turn, text, intent, entities, response
                )
            except Exception as e:
                logger.warning(f"Failed to store turn in memory: {e}")
        
        return CommandResult(
            intent=intent,
            entities=entities,
            action_result=action_result,
            response=response,
            used_local_classifier=used_local
        )
        
    async def _handle_confirmation(self, text: str, session: UserSession) -> CommandResult:
        """Handle Yes/No responses for pending actions."""
        text_lower = text.strip().lower()
        is_yes = any(word in text_lower for word in ["yes", "confirm", "delete all", "proceed", "haan", "ha"])
        is_no = any(word in text_lower for word in ["no", "cancel", "abort", "nahi", "mat karo"])
        
        if is_yes and session.pending_action == "delete_events":
            entities = session.pending_data or {}
            calendar_mgr = session.calendar_manager
            
            if calendar_mgr:
                action_result = await self._execute_confirmed_bulk_delete(
                    calendar_mgr, entities
                )
            else:
                action_result = "Please sign in with Google."
                
            self._clear_confirmation(session)
            
            return CommandResult(
                intent="delete_event",
                entities=entities,
                action_result=action_result,
                response=action_result,
                used_local_classifier=True
            )
            
        elif is_no:
            self._clear_confirmation(session)
            return CommandResult(
                intent=None,
                entities={},
                action_result="Operation cancelled.",
                response="Okay, I've cancelled that operation.",
                used_local_classifier=True
            )
            
        else:
            # Not a confirmation, treat as a new command
            self._clear_confirmation(session)
            # Re-process as a normal command
            return await self.process_command(text, self.nlp.user_name, str(self.nlp.local_tz), session)
            
    async def _execute_confirmed_bulk_delete(
        self, calendar_mgr, entities: dict
    ) -> str:
        """
        Execute a confirmed bulk delete operation using the stored event IDs.
        The event_ids were captured during the initial delete request and
        stored in session.pending_data by the confirmation handler.
        """
        event_ids = entities.get('event_ids')
        
        if not event_ids:
            return "Could not determine which events to delete. Please try again with a specific time range."
        
        service = calendar_mgr._get_calendar_service()
        if not service:
            return "Calendar service unavailable. Please re-authenticate."
        
        try:
            return await asyncio.to_thread(
                calendar_mgr._delete_by_ids, service, event_ids
            )
        except Exception as e:
            logger.error(f"Confirmed bulk delete failed: {e}", exc_info=True)
            return f"Error during bulk deletion: {str(e)}"

    def _clear_confirmation(self, session: UserSession):
        """Reset the confirmation state machine on the given session."""
        session.awaiting_confirmation = False
        session.pending_action = None
        session.pending_data = None
