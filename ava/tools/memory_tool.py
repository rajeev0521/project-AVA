from typing import Any, Dict
from ava.tools.base_tool import BaseTool
from ava.memory.long_term_memory import LongTermMemory
from ava.conversation.state_manager import UserSession

class MemoryToolBase(BaseTool):
    """Base class for Memory tools."""
    def _get_memory(self, session):
        if not session or not hasattr(session, "memory_manager") or not session.memory_manager:
            raise ValueError("Long term memory not initialized. Supabase might be disabled.")
        return session.memory_manager

class SaveUserPreferenceTool(MemoryToolBase):
    @property
    def name(self) -> str:
        return "save_user_preference"
        
    @property
    def description(self) -> str:
        return (
            "Save a persistent rule or preference explicitly stated by the user. "
            "Use this ONLY when the user gives an explicit standing rule (e.g., 'My internship meetings are 1 hour', 'I prefer morning meetings'). "
            "Do NOT use this for transient context, emotions, or one-off statements. "
            "The 'key' should be a stable snake_case identifier representing the preference category so future updates overwrite the same key."
        )
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string", 
                    "description": "Stable snake_case canonical identifier (e.g., 'internship_meeting_duration', 'preferred_morning_start')."
                },
                "content": {
                    "type": "string", 
                    "description": "The full human-readable sentence of the preference (e.g., 'Internship meetings are always 1 hour long.')."
                }
            },
            "required": ["key", "content"]
        }
        
    async def execute(self, session, **kwargs) -> Any:
        key = kwargs.get("key")
        content = kwargs.get("content")
        
        user_id = session.user_id if session else "default"
        try:
            memory = self._get_memory(session)
            success = memory.save_preference(user_id, key, content)
            if success:
                return {"status": "success", "message": f"Saved preference '{key}'."}
            else:
                return {"error": "Failed to save preference."}
        except Exception as e:
            return {"error": str(e)}

class ListUserPreferencesTool(MemoryToolBase):
    @property
    def name(self) -> str:
        return "list_user_preferences"
        
    @property
    def description(self) -> str:
        return (
            "List all persistent preferences currently saved about the user. "
            "Trigger this when the user asks what AVA remembers or wants to see their preferences."
        )
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }
        
    async def execute(self, session, **kwargs) -> Any:
        user_id = session.user_id if session else "default"
        
        try:
            memory = self._get_memory(session)
            preferences = memory.list_preferences(user_id)
            if preferences:
                return {
                    "status": "success",
                    "count": len(preferences),
                    "preferences": [{"key": p.key, "content": p.content} for p in preferences]
                }
            else:
                return {"status": "success", "count": 0, "preferences": [], "message": "No preferences saved."}
        except Exception as e:
            return {"error": str(e)}

class DeleteUserPreferenceTool(MemoryToolBase):
    @property
    def name(self) -> str:
        return "delete_user_preference"
        
    @property
    def description(self) -> str:
        return (
            "Delete a specific user preference by its key. "
            "Trigger this when the user explicitly asks to forget a preference."
        )
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The snake_case key of the preference to delete."}
            },
            "required": ["key"]
        }
        
    async def execute(self, session, **kwargs) -> Any:
        key = kwargs.get("key")
        user_id = session.user_id if session else "default"
        
        try:
            memory = self._get_memory(session)
            success = memory.delete_preference(user_id, key)
            if success:
                return {"status": "success", "message": f"Deleted preference '{key}'."}
            else:
                return {"error": "Failed to delete preference."}
        except Exception as e:
            return {"error": str(e)}
