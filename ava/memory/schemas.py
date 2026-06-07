from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

class MemoryEntry(BaseModel):
    """Represents a long-term user preference."""
    id: Optional[str] = None
    user_id: str
    key: str
    content: str
    embedding_model: str = "text-embedding-004"
    source: str = "user_explicit"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    similarity: Optional[float] = None

class SessionState(BaseModel):
    """Serializable snapshot of ConversationState for Redis."""
    session_id: str
    user_id: str
    pending_action: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    draft_event: Optional[Dict[str, Any]] = None
    last_event: Optional[Any] = None
    turn_count: int = 0
    saved_at: str  # ISO 8601 UTC timestamp
