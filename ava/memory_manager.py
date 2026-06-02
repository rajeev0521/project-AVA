"""
Memory Manager for AVA — Supabase PostgreSQL backend.
Provides conversation history, entity context, and reference resolution.
"""

import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from .logger import get_logger

logger = get_logger(__name__)


class MemoryManager:
    """
    Persistent conversational memory backed by Supabase PostgreSQL.
    
    Features:
        - Conversation history (last N turns per user)
        - Entity context tracking (last referenced event)
        - Pronoun/reference resolution ("it", "that meeting", etc.)
        - User preference learning
    
    Requires Supabase tables: users, conversations, entity_context
    """
    
    # Max turns to include in LLM context
    MAX_CONTEXT_TURNS = 10
    
    def __init__(self, supabase_client, user_id: str):
        """
        Initialize memory manager.
        
        Args:
            supabase_client: Shared Supabase client instance (created once in api.py)
            user_id: Current user's ID
        """
        self.supabase = supabase_client
        self.user_id = user_id
        
        # In-memory cache of recent turns (avoids DB round-trips)
        self._conversation_cache: List[Dict] = []
        self._entity_context: Dict[str, Any] = {}
        self._history_loaded = False
        
        logger.info(f"MemoryManager initialized for user={user_id}")
    
    def _load_session_history(self, limit: int = None):
        """Load recent conversation history from Supabase into cache."""
        if self._history_loaded:
            return
            
        limit = limit or self.MAX_CONTEXT_TURNS
        try:
            response = (
                self.supabase.table("conversations")
                .select("user_input, intent, entities, response, created_at")
                .eq("user_id", self.user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            
            if response.data:
                # Reverse so oldest is first
                self._conversation_cache = list(reversed(response.data))
                logger.info(f"Loaded {len(self._conversation_cache)} turns from history")
                
                # Restore entity context from most recent turn
                if self._conversation_cache:
                    last = self._conversation_cache[-1]
                    if last.get("entities"):
                        entities = last["entities"]
                        if isinstance(entities, str):
                            entities = json.loads(entities)
                        self._entity_context = entities
            else:
                self._conversation_cache = []
                
        except Exception as e:
            logger.warning(f"Failed to load session history: {e}")
            self._conversation_cache = []
            
        self._history_loaded = True
    
    def add_turn(self, user_input: str, intent: Optional[str], 
                 entities: Optional[Dict], response: str):
        """
        Store a conversation turn in Supabase and update local cache.
        
        Args:
            user_input: What the user said
            intent: Detected intent
            entities: Extracted entities
            response: AVA's response
        """
        turn = {
            "user_id": self.user_id,
            "user_input": user_input,
            "intent": intent,
            "entities": json.dumps(entities) if entities else None,
            "response": response,
        }
        
        # Update local cache
        cache_entry = {
            "user_input": user_input,
            "intent": intent,
            "entities": entities or {},
            "response": response,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._conversation_cache.append(cache_entry)
        
        # Trim cache to max size
        if len(self._conversation_cache) > self.MAX_CONTEXT_TURNS:
            self._conversation_cache = self._conversation_cache[-self.MAX_CONTEXT_TURNS:]
        
        # Update entity context
        if entities:
            self._entity_context = entities
        
        # Store in Supabase (async-friendly, non-blocking intent)
        try:
            self.supabase.table("conversations").insert(turn).execute()
            
            # Also update entity context table
            if entities:
                self._update_entity_context(entities)
                
        except Exception as e:
            logger.warning(f"Failed to store turn in Supabase: {e}")
    
    def _update_entity_context(self, entities: Dict):
        """Update the entity context in Supabase."""
        try:
            # Upsert entity context
            data = {
                "user_id": self.user_id,
                "entity_type": "last_event",
                "entity_data": json.dumps(entities),
            }
            
            # Try to update existing, insert if not found
            existing = (
                self.supabase.table("entity_context")
                .select("id")
                .eq("user_id", self.user_id)
                .eq("entity_type", "last_event")
                .execute()
            )
            
            if existing.data:
                (
                    self.supabase.table("entity_context")
                    .update({"entity_data": json.dumps(entities), "updated_at": datetime.now(timezone.utc).isoformat()})
                    .eq("id", existing.data[0]["id"])
                    .execute()
                )
            else:
                self.supabase.table("entity_context").insert(data).execute()
                
        except Exception as e:
            logger.warning(f"Failed to update entity context: {e}")
    
    def get_context_prompt(self) -> str:
        """
        Build a context string from recent conversation history
        suitable for injection into the LLM prompt.
        
        Returns:
            Formatted conversation history string
        """
        self._load_session_history()
        
        if not self._conversation_cache:
            return "No previous conversation."
        
        lines = []
        for turn in self._conversation_cache[-self.MAX_CONTEXT_TURNS:]:
            entities = turn.get("entities", {})
            if isinstance(entities, str):
                try:
                    entities = json.loads(entities)
                except (json.JSONDecodeError, TypeError):
                    entities = {}
            
            intent = turn.get("intent", "unknown")
            user_input = turn.get("user_input", "")
            response = turn.get("response", "")
            
            lines.append(f"User: {user_input}")
            lines.append(f"AVA: {response}")
            if entities:
                # Include key entity info for reference resolution
                entity_summary = ", ".join(
                    f"{k}={v}" for k, v in entities.items() 
                    if k in ['title', 'start_time', 'end_time', 'event_id']
                )
                if entity_summary:
                    lines.append(f"[Context: intent={intent}, {entity_summary}]")
            lines.append("")
        
        return "\n".join(lines).strip()
    
    def resolve_reference(self, command: str) -> str:
        """
        Resolve pronoun references in user commands using entity context.
        
        Examples:
            "move it to 3 PM" → "move [Team Meeting] to 3 PM"
            "delete that" → "delete [Team Meeting]"
            "same time tomorrow" → provides context about the referenced time
        
        Args:
            command: Raw user command
            
        Returns:
            Command with resolved references (or original if no resolution needed)
        """
        self._load_session_history()
        
        if not self._entity_context:
            return command
        
        command_lower = command.lower()
        
        # Pronouns and references to resolve
        reference_patterns = [
            # English
            "it", "that", "that event", "that meeting", "the meeting", 
            "the event", "this event", "this meeting",
            # Hindi/Hinglish
            "woh", "usse", "isko", "usko", "wo meeting", "wo event",
        ]
        
        has_reference = any(ref in command_lower for ref in reference_patterns)
        
        if not has_reference:
            return command
        
        # Build context annotation
        last_title = self._entity_context.get('title', '')
        last_start = self._entity_context.get('start_time', '')
        last_end = self._entity_context.get('end_time', '')
        last_event_id = self._entity_context.get('event_id', '')
        
        context_parts = []
        if last_title:
            context_parts.append(f"(referring to event: '{last_title}')")
        if last_event_id:
            context_parts.append(f"(event_id: {last_event_id})")
        
        if context_parts:
            resolved = f"{command} {' '.join(context_parts)}"
            logger.info(f"Resolved reference: '{command}' → '{resolved}'")
            return resolved
        
        return command
    
    def get_user_preferences(self) -> Dict[str, Any]:
        """
        Learn user patterns from conversation history.
        
        Returns:
            Dict of learned preferences (e.g., typical meeting duration, common times)
        """
        preferences = {}
        
        try:
            # Query recent create_event intents to learn patterns
            response = (
                self.supabase.table("conversations")
                .select("entities")
                .eq("user_id", self.user_id)
                .eq("intent", "create_event")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            
            if response.data:
                # Analyze common meeting durations, times, etc.
                durations = []
                for row in response.data:
                    entities = row.get("entities", {})
                    if isinstance(entities, str):
                        try:
                            entities = json.loads(entities)
                        except (json.JSONDecodeError, TypeError):
                            continue
                    
                    start = entities.get("start_time")
                    end = entities.get("end_time")
                    if start and end:
                        try:
                            from datetime import datetime as dt
                            start_dt = dt.fromisoformat(start)
                            end_dt = dt.fromisoformat(end)
                            duration_min = (end_dt - start_dt).total_seconds() / 60
                            durations.append(duration_min)
                        except (ValueError, TypeError):
                            pass
                
                if durations:
                    avg_duration = sum(durations) / len(durations)
                    preferences["avg_meeting_duration_minutes"] = round(avg_duration)
                    
        except Exception as e:
            logger.warning(f"Failed to get user preferences: {e}")
        
        return preferences
    
    def clear_context(self):
        """Clear the current entity context (e.g., when starting a new topic)."""
        self._entity_context = {}
        logger.info("Entity context cleared")
