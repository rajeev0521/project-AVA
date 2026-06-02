"""
AVA — Voice-Based AI Calendar Assistant
Main entry point for desktop mode.
"""

import os
import sys
import time
from dotenv import load_dotenv

from .voice_processor import VoiceProcessor
from .calendar_manager import CalendarManager
from .nlp_processor import NLPProcessor
from .auth_manager import AuthManager
from .config import config
from .logger import get_logger

logger = get_logger(__name__)

# Follow-up window: seconds to listen without wake word after a response
FOLLOW_UP_WINDOW = 8.0


class AVASession:
    """Tracks session state for multi-turn conversations."""
    
    def __init__(self):
        self.awaiting_confirmation = False
        self.pending_action = None
        self.pending_data = None
        self.last_intent = None
        self.last_entities = None
        self.last_response_time = 0.0  # Timestamp of last response for follow-up window


class AVA:
    """Main AVA assistant orchestrator."""
    
    def __init__(self):
        load_dotenv()
        
        logger.info("Initializing AVA...")
        
        # In desktop mode, Supabase may not be configured — use null token store
        from .token_store import NullTokenStore
        self.auth_manager = AuthManager(token_store=NullTokenStore())
        self.voice_processor = VoiceProcessor()
        self.calendar_manager = CalendarManager(self.auth_manager)
        
        # Initialize memory manager (Supabase) if configured
        self.memory_manager = self._init_memory()
        
        # NLP processor with memory integration
        self.nlp_processor = NLPProcessor(memory_manager=self.memory_manager)
        self.session = AVASession()
        
        logger.info("AVA initialized successfully!")
        
    def _init_memory(self):
        """Initialize Supabase memory manager if credentials are available."""
        try:
            supabase_url = config.supabase_url
            supabase_key = config.supabase_key
            
            if supabase_url and supabase_key:
                from .memory_manager import MemoryManager
                from supabase import create_client
                supabase_client = create_client(supabase_url, supabase_key)
                user_id = os.getenv("AVA_USER_ID", "default")
                memory = MemoryManager(supabase_client, user_id)
                logger.info("Supabase memory manager connected")
                return memory
            else:
                logger.info("Supabase not configured — running without persistent memory")
                return None
        except Exception as e:
            logger.warning(f"Memory manager init failed: {e}. Running without memory.")
            return None
        
    def start(self):
        """Main event loop for desktop mode."""
        logger.info("AVA is listening...")
        print("\n🎙️  AVA is ready. Say the wake word to start!\n")
        
        while True:
            try:
                # If awaiting confirmation, listen directly (no wake word needed)
                if self.session.awaiting_confirmation:
                    command = self.voice_processor.listen_command()
                    if command:
                        self._handle_confirmation(command)
                    continue

                # Check if we're within the follow-up window (no wake word needed)
                in_follow_up = (time.time() - self.session.last_response_time) < FOLLOW_UP_WINDOW
                
                if in_follow_up:
                    logger.info("Follow-up window active — listening without wake word...")
                    command = self.voice_processor.listen_command()
                    if command:
                        self._process_command(command)
                    else:
                        # No command heard, exit follow-up mode
                        self.session.last_response_time = 0.0
                    continue

                # Normal flow: wait for wake word
                if self.voice_processor.detect_wake_word():
                    logger.info("Wake word detected! Awaiting command...")
                    print("✨ Wake word detected! How can I help you?")
                    command = self.voice_processor.listen_command()
                    if command:
                        self._process_command(command)

            except KeyboardInterrupt:
                logger.info("Shutting down AVA...")
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(1)

    def _process_command(self, command: str):
        """Process a voice command through the NLP pipeline."""
        logger.info(f"Processing command: {command}")
        print(f"📝 You said: {command}")
        
        # Process command using NLP (returns intent, entities, response_template)
        intent, entities, response_template = self.nlp_processor.process_command(command)
        
        self.session.last_intent = intent
        self.session.last_entities = entities
        
        if intent:
            # Execute calendar operation
            action_result = self.calendar_manager.execute_command(intent, entities)
            
            # Check for bulk delete confirmation
            if (
                intent == "delete_event" and
                "Please confirm if you want to delete all these events" in action_result
            ):
                event_ids = self.calendar_manager.get_pending_delete_event_ids()
                self.session.awaiting_confirmation = True
                self.session.pending_action = "delete_events"
                self.session.pending_data = event_ids
                self.voice_processor.speak(action_result)
                self.session.last_response_time = time.time()
                return
            
            # Generate natural language response
            response = self.nlp_processor.generate_response(
                action_result, intent, entities, response_template
            )
        else:
            response = "I'm sorry, I couldn't understand what you want me to do with your calendar."
        
        # Speak response
        self.voice_processor.speak(response)
        self.session.last_response_time = time.time()
        
        # Store turn in memory
        if self.memory_manager:
            try:
                self.memory_manager.add_turn(command, intent, entities, response)
            except Exception as e:
                logger.warning(f"Failed to store turn in memory: {e}")

    def _handle_confirmation(self, command: str):
        """Handle confirmation responses for pending actions."""
        if command.strip().lower() in ["yes", "confirm", "delete all", "proceed", "haan", "ha"]:
            if self.session.pending_action == "delete_events":
                event_ids = self.session.pending_data
                if event_ids:
                    service = self.calendar_manager._get_calendar_service()
                    if service:
                        result = self.calendar_manager._delete_by_ids(service, event_ids)
                    else:
                        result = "Calendar service unavailable. Please re-authenticate."
                else:
                    result = "Could not determine which events to delete. Please try again."
                self._clear_confirmation()
                self.voice_processor.speak(result)
                self.session.last_response_time = time.time()
                return
        elif command.strip().lower() in ["no", "cancel", "abort", "nahi", "mat karo"]:
            self.voice_processor.speak("Okay, no events were deleted.")
            self._clear_confirmation()
            self.session.last_response_time = time.time()
            return
        else:
            # Not a confirmation, treat as a new command
            self._clear_confirmation()
            self._process_command(command)

    def _clear_confirmation(self):
        """Clear confirmation state."""
        self.session.awaiting_confirmation = False
        self.session.pending_action = None
        self.session.pending_data = None


if __name__ == "__main__":
    ava = AVA()
    ava.start()