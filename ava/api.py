"""
AVA API Server — FastAPI backend for web deployment.
Provides REST + WebSocket endpoints for the AVA assistant.
Supports multi-user authentication via Google OAuth.
"""

import os
import json
import sys
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Ensure ava directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nlp_processor import NLPProcessor
from calendar_manager import CalendarManager
from auth_manager import AuthManager
from memory_manager import MemoryManager
from rate_limiter import RateLimiter, RateLimitExceeded
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

# ── App Setup ──────────────────────────────────────────────────────

app = FastAPI(
    title="AVA — AI Calendar Assistant",
    description="Voice-activated AI calendar assistant API",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global State ───────────────────────────────────────────────────

rate_limiter = RateLimiter()

# Per-user session cache (in production, use Redis)
user_sessions: Dict[str, Dict[str, Any]] = {}


def get_user_session(user_id: str) -> Dict[str, Any]:
    """Get or create a user session with all components."""
    if user_id not in user_sessions:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        memory = None
        if supabase_url and supabase_key:
            try:
                memory = MemoryManager(supabase_url, supabase_key, user_id)
            except Exception as e:
                logger.warning(f"Memory init failed for user {user_id}: {e}")
        
        auth_manager = AuthManager()
        
        user_sessions[user_id] = {
            "nlp": NLPProcessor(memory_manager=memory),
            "calendar": CalendarManager(auth_manager),
            "memory": memory,
            "last_intent": None,
            "last_entities": None,
        }
        logger.info(f"Created session for user: {user_id}")
    
    return user_sessions[user_id]


# ── Request/Response Models ────────────────────────────────────────

class CommandRequest(BaseModel):
    """Request body for processing a text command."""
    text: str
    user_id: str = "default"
    user_name: Optional[str] = None


class CommandResponse(BaseModel):
    """Response body after processing a command."""
    intent: Optional[str]
    entities: Dict[str, Any]
    action_result: str
    response: str
    used_local_classifier: bool = False


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    daily_api_remaining: int


# ── API Endpoints ──────────────────────────────────────────────────

@app.get("/", response_class=FileResponse)
async def serve_frontend():
    """Serve the frontend HTML."""
    frontend_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frontend", "index.html"
    )
    if os.path.exists(frontend_path):
        return FileResponse(frontend_path)
    return {"message": "AVA API is running. Frontend not found."}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="2.0.0",
        daily_api_remaining=rate_limiter.daily_remaining,
    )


@app.post("/api/command", response_model=CommandResponse)
async def process_command(request: CommandRequest):
    """
    Process a text command and return the result.
    
    This is the main endpoint for the AVA assistant.
    Accepts natural language commands and returns structured results.
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty command")
    
    session = get_user_session(request.user_id)
    nlp: NLPProcessor = session["nlp"]
    calendar: CalendarManager = session["calendar"]
    memory: Optional[MemoryManager] = session["memory"]
    
    if request.user_name:
        nlp.set_user_name(request.user_name)
    
    try:
        # Check rate limit
        wait_time = rate_limiter.wait_if_needed()
        if wait_time > 0:
            import asyncio
            await asyncio.sleep(wait_time)
        
        # Process command through NLP pipeline
        intent, entities, response_template = nlp.process_command(request.text)
        
        # Track if we used local classifier (for metrics)
        used_local = bool(response_template and intent)
        
        # Record API usage if we hit Gemini
        if not used_local:
            rate_limiter.record_request()
        
        action_result = ""
        if intent:
            # Execute calendar operation
            action_result = calendar.execute_command(intent, entities)
            
            # Generate response
            response = nlp.generate_response(action_result, intent, entities, response_template)
        else:
            response = "I'm sorry, I couldn't understand what you want me to do with your calendar."
        
        # Store in memory
        if memory and intent:
            try:
                memory.add_turn(request.text, intent, entities, response)
            except Exception as e:
                logger.warning(f"Failed to store in memory: {e}")
        
        # Update session state
        session["last_intent"] = intent
        session["last_entities"] = entities
        
        return CommandResponse(
            intent=intent,
            entities=entities,
            action_result=action_result,
            response=response,
            used_local_classifier=used_local,
        )
        
    except RateLimitExceeded:
        raise HTTPException(
            status_code=429,
            detail="Daily API limit reached. Please try again tomorrow."
        )
    except Exception as e:
        logger.error(f"Error processing command: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time interaction.
    Supports streaming text commands and responses.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: user={user_id}")
    
    session = get_user_session(user_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            command = message.get("text", "")
            if not command:
                await websocket.send_json({"error": "Empty command"})
                continue
            
            # Process through the same pipeline
            nlp: NLPProcessor = session["nlp"]
            calendar: CalendarManager = session["calendar"]
            memory: Optional[MemoryManager] = session["memory"]
            
            user_name = message.get("user_name")
            if user_name:
                nlp.set_user_name(user_name)
            
            try:
                intent, entities, response_template = nlp.process_command(command)
                
                action_result = ""
                if intent:
                    action_result = calendar.execute_command(intent, entities)
                    response = nlp.generate_response(action_result, intent, entities, response_template)
                else:
                    response = "I couldn't understand that. Could you rephrase?"
                
                if memory and intent:
                    try:
                        memory.add_turn(command, intent, entities, response)
                    except Exception:
                        pass
                
                await websocket.send_json({
                    "type": "response",
                    "intent": intent,
                    "response": response,
                    "action_result": action_result,
                })
                
            except RateLimitExceeded:
                await websocket.send_json({
                    "type": "error",
                    "message": "Daily API limit reached.",
                })
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user={user_id}")
    except Exception as e:
        logger.error(f"WebSocket fatal error: {e}")


@app.get("/api/events")
async def get_events(
    user_id: str = "default",
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """Get calendar events for a date range."""
    session = get_user_session(user_id)
    calendar: CalendarManager = session["calendar"]
    
    entities = {}
    if start:
        entities["start_time"] = start
    if end:
        entities["end_time"] = end
    
    result = calendar.read_events(entities)
    return {"events": result}


@app.get("/api/stats")
async def get_stats():
    """Get API usage statistics."""
    return {
        "active_sessions": len(user_sessions),
        "daily_api_remaining": rate_limiter.daily_remaining,
        "rate_limiter_can_request": rate_limiter.can_make_request,
    }


# ── Serve Static Files (Frontend) ─────────────────────────────────

frontend_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend"
)
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


# ── Development Server ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
