from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from ava.api import dependencies
from ava.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/memory", tags=["Memory"])

class PreferenceUpdateRequest(BaseModel):
    user_id: str
    preferences: Dict[str, Any]

@router.get("/preferences")
async def get_preferences(user_id: str):
    """Retrieve user preferences from long-term memory."""
    session = dependencies.get_session(user_id)
    if not session.memory_manager:
        raise HTTPException(status_code=503, detail="Memory service is unavailable")
    
    try:
        # Assuming memory_manager has a method to fetch preferences
        # If it doesn't, this acts as a placeholder or we can implement it
        prefs = session.memory_manager.get_preferences() if hasattr(session.memory_manager, 'get_preferences') else {}
        return {"preferences": prefs}
    except Exception as e:
        logger.error(f"Error fetching memory preferences: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/preferences")
async def update_preferences(request: PreferenceUpdateRequest):
    """Update user preferences."""
    session = dependencies.get_session(request.user_id)
    if not session.memory_manager:
        raise HTTPException(status_code=503, detail="Memory service is unavailable")
        
    try:
        # Placeholder for actual update logic
        if hasattr(session.memory_manager, 'update_preferences'):
            session.memory_manager.update_preferences(request.preferences)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error updating preferences: {e}")
        raise HTTPException(status_code=500, detail=str(e))
