from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio

from ava.api import dependencies
from ava.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])

class EventCreateRequest(BaseModel):
    user_id: str
    title: str
    start_datetime: str
    end_datetime: str
    description: str = ""

@router.get("/events")
async def list_events(user_id: str, max_results: int = 10):
    """List upcoming calendar events."""
    session = dependencies.get_session(user_id)
    if not session.calendar_manager:
        raise HTTPException(status_code=401, detail="Google authentication required")
    
    try:
        events = await asyncio.to_thread(
            session.calendar_manager.read_events, 
            {"max_results": max_results}
        )
        return {"events": events}
    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/events")
async def create_event(request: EventCreateRequest):
    """Create a new calendar event."""
    session = dependencies.get_session(request.user_id)
    if not session.calendar_manager:
        raise HTTPException(status_code=401, detail="Google authentication required")
    
    try:
        result = await asyncio.to_thread(
            session.calendar_manager.create_event,
            request.title,
            request.start_datetime,
            request.end_datetime,
            request.description
        )
        return {"status": "success", "event": result}
    except Exception as e:
        logger.error(f"Error creating calendar event: {e}")
        raise HTTPException(status_code=500, detail=str(e))
