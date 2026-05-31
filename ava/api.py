import os
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from supabase import create_client

from .logger import get_logger
from .auth_manager import AuthManager
from .token_store import SupabaseTokenStore
from .memory_manager import MemoryManager
from .calendar_manager import CalendarManager
from .nlp_processor import NLPProcessor
from .rate_limiter import RateLimiter, RateLimitExceeded
from .session_manager import SessionManager
from .command_service import CommandService

logger = get_logger(__name__)

# Global state initialized in lifespan
supabase = None
auth_manager = None
rate_limiter = None
session_manager = None
nlp_processor = None
command_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for global resources."""
    global supabase, auth_manager, rate_limiter, session_manager, nlp_processor, command_service
    
    logger.info("Starting AVA API server...")
    
    # 1. Initialize Supabase (Shared Client)
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        logger.error("Supabase credentials missing! Features requiring persistence will fail.")
    else:
        supabase = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized")
    
    # 2. Initialize Auth Manager
    if supabase:
        token_store = SupabaseTokenStore(supabase)
        auth_manager = AuthManager(token_store=token_store)
    else:
        # Fallback for local testing without DB
        class DummyTokenStore:
            def save(self, *args): pass
            def load(self, *args): return None
            def delete(self, *args): pass
            def exists(self, *args): return False
        auth_manager = AuthManager(token_store=DummyTokenStore())
        
    # 3. Initialize Rate Limiter & Session Manager
    rate_limiter = RateLimiter(max_rpm=15, max_rpd=1500)
    session_manager = SessionManager(max_sessions=100, ttl_seconds=1800)
    
    # 4. Initialize Shared NLP Processor & Command Service
    nlp_processor = NLPProcessor()
    command_service = CommandService(nlp_processor)
    
    logger.info("AVA API server successfully started")
    yield
    
    logger.info("Shutting down AVA API server...")


app = FastAPI(
    title="AVA Calendar Assistant API",
    description="Backend API for AVA voice-activated calendar assistant",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Models ---

class CommandRequest(BaseModel):
    text: str
    user_id: str
    user_name: str = "User"
    timezone: str = ""


# --- Helper Methods ---

def _get_or_create_session(user_id: str):
    """Retrieve existing session or create a new one with required managers."""
    session = session_manager.get_session(user_id)
    
    if not session:
        # Create user-specific managers
        memory_mgr = MemoryManager(supabase, user_id) if supabase else None
        calendar_mgr = CalendarManager(auth_manager, user_id)
        
        session = session_manager.create_session(user_id, memory_mgr, calendar_mgr)
        
    return session


# --- API Routes ---

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "daily_api_remaining": rate_limiter.daily_remaining if rate_limiter else 1500
    }

@app.get("/api/stats")
async def api_stats():
    """Get current API stats and rate limit info."""
    if not rate_limiter or not session_manager:
        return {"status": "initializing"}
        
    return {
        **session_manager.get_stats(),
        "daily_api_remaining": rate_limiter.daily_remaining,
        "rate_limiter_can_request": rate_limiter.can_make_request,
    }


# --- Command Endpoints ---

@app.post("/api/command")
async def process_command(request: CommandRequest):
    """Process a natural language command via REST."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Command text cannot be empty")
        
    try:
        # Rate Limiting
        await rate_limiter.wait_if_needed_async()
        rate_limiter.record_request()
        
        # Get Session
        session = _get_or_create_session(request.user_id)
        
        # Process Command
        result = await command_service.process_command(
            text=request.text,
            user_name=request.user_name,
            timezone_str=request.timezone,
            session=session
        )
        
        return result.model_dump()
        
    except RateLimitExceeded:
        raise HTTPException(
            status_code=429, 
            detail="Daily Gemini API limit reached (1500 requests). Please try again tomorrow."
        )
    except Exception as e:
        logger.error(f"Error processing REST command: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """Process natural language commands via WebSocket."""
    await websocket.accept()
    logger.info(f"WebSocket connected for user {user_id}")
    
    session = _get_or_create_session(user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "").strip()
            user_name = data.get("user_name", "User")
            timezone_str = data.get("timezone", "")
            
            if not text:
                continue
                
            try:
                # Rate Limiting
                wait_time = rate_limiter.check_rate_limit()
                if wait_time > 0:
                    await websocket.send_json({
                        "type": "warning",
                        "message": f"Rate limit approached. Waiting {wait_time:.1f}s..."
                    })
                    await rate_limiter.wait_if_needed_async()
                    
                rate_limiter.record_request()
                
                # Process Command
                result = await command_service.process_command(
                    text=text,
                    user_name=user_name,
                    timezone_str=timezone_str,
                    session=session
                )
                
                # Send Response
                response_data = result.model_dump()
                response_data["type"] = "response"
                await websocket.send_json(response_data)
                
            except RateLimitExceeded:
                await websocket.send_json({
                    "type": "error",
                    "message": "Daily API limit reached. Please try again tomorrow."
                })
            except Exception as e:
                logger.error(f"Error processing WS command: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": f"Error: {str(e)}"
                })
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        try:
            await websocket.close()
        except:
            pass


@app.get("/api/events")
async def get_events(user_id: str):
    """Get upcoming events for a user (used by frontend calendar widget)."""
    session = _get_or_create_session(user_id)
    
    if not session.calendar_manager:
        raise HTTPException(status_code=401, detail="Please sign in with Google first.")
        
    try:
        # Default read_events behavior is next 7 days
        events_str = await asyncio.to_thread(
            session.calendar_manager.read_events, {}
        )
        return {"events": events_str}
    except Exception as e:
        logger.error(f"Error reading events for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- OAuth Routes ---

@app.get("/auth/login")
async def login():
    """Start Google OAuth flow."""
    if not auth_manager:
        raise HTTPException(status_code=500, detail="Auth manager not initialized")
    
    state = "random_state_token_for_csrf"
    url, code_verifier = auth_manager.get_authorization_url(state)
    return RedirectResponse(url)


@app.get("/auth/callback")
async def auth_callback(code: str, state: str):
    """Handle Google OAuth callback."""
    if not auth_manager:
        raise HTTPException(status_code=500, detail="Auth manager not initialized")
    
    try:
        # Exchange code for credentials
        creds = auth_manager.exchange_code(code)
        
        # Get user info (requires openid and email scopes)
        user_info = auth_manager.get_user_info(creds)
        user_id = user_info.get("id")
        
        if not user_id:
            logger.error("Could not get user ID from Google")
            return RedirectResponse("/?error=no_user_id")
        
        # Save credentials to Supabase
        from .auth_manager import creds_to_dict
        auth_manager.token_store.save(user_id, creds_to_dict(creds))
        
        # Pre-warm session
        _get_or_create_session(user_id)
        
        logger.info(f"User {user_id} logged in successfully")
        
        # Redirect back to frontend with user info in URL params
        name = user_info.get("name", "User")
        picture = user_info.get("picture", "")
        
        from urllib.parse import urlencode
        params = urlencode({
            "user_id": user_id, 
            "name": name,
            "picture": picture
        })
        
        # Assuming frontend is served from root or same origin
        return RedirectResponse(f"/?{params}")
        
    except Exception as e:
        logger.error(f"OAuth callback failed: {e}", exc_info=True)
        return RedirectResponse(f"/?error={str(e)}")


@app.get("/auth/logout")
async def logout(request: Request):
    """Log out user and revoke tokens."""
    # Since this is a simple GET for now, we don't have user_id easily available
    # In a real app, you'd get this from a JWT cookie or session
    # For now, frontend just clears local storage and calls this
    return RedirectResponse("/")
