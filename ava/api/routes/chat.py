"""
AVA Chat Routes — REST and WebSocket endpoints for natural language commands.
"""

import secrets
from typing import Dict
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ava.logger import get_logger
from ava.rate_limiter import RateLimitExceeded
from ava.calendar.auth import creds_to_dict
from ava.api import dependencies

logger = get_logger(__name__)

router = APIRouter()


# --- Models ---

class CommandRequest(BaseModel):
    text: str
    user_id: str
    user_name: str = "User"
    timezone: str = ""


# --- API Routes ---

@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "daily_api_remaining": dependencies.rate_limiter.daily_remaining if dependencies.rate_limiter else 1500,
    }


@router.get("/api/stats")
async def api_stats():
    """Get current API stats and rate limit info."""
    if not dependencies.rate_limiter or not dependencies.session_manager:
        return {"status": "initializing"}

    return {
        **dependencies.session_manager.get_stats(),
        "daily_api_remaining": dependencies.rate_limiter.daily_remaining,
        "rate_limiter_can_request": dependencies.rate_limiter.can_make_request,
    }


# --- Command Endpoints ---

@router.post("/api/command")
async def process_command(request: CommandRequest):
    """Process a natural language command via REST."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Command text cannot be empty")

    try:
        # Rate Limiting
        await dependencies.rate_limiter.wait_if_needed_async()
        dependencies.rate_limiter.record_request()

        # Get Session
        session = dependencies.get_session(request.user_id)

        # Process Command
        result = await dependencies.command_service.process_command(
            text=request.text,
            user_name=request.user_name,
            timezone_str=request.timezone,
            session=session,
        )

        result_dict = result.model_dump()
        result_dict["response"] = result_dict["text"]
        return result_dict

    except RateLimitExceeded:
        raise HTTPException(
            status_code=429,
            detail="Daily Gemini API limit reached (1500 requests). Please try again tomorrow.",
        )
    except Exception as e:
        logger.error(f"Error processing REST command: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """Process natural language commands via WebSocket."""
    await websocket.accept()
    logger.info(f"WebSocket connected for user {user_id}")

    session = dependencies.get_session(user_id)

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
                wait_time = dependencies.rate_limiter.check_rate_limit()
                if wait_time > 0:
                    await websocket.send_json({
                        "type": "warning",
                        "message": f"Rate limit approached. Waiting {wait_time:.1f}s...",
                    })
                    await dependencies.rate_limiter.wait_if_needed_async()

                dependencies.rate_limiter.record_request()

                # Process Command
                result = await dependencies.command_service.process_command(
                    text=text,
                    user_name=user_name,
                    timezone_str=timezone_str,
                    session=session,
                )

                # Send Response
                response_data = result.model_dump()
                response_data["type"] = "response"
                response_data["response"] = response_data["text"]
                logger.info(f"Sending WS response to {user_id}: {response_data}")
                await websocket.send_json(response_data)

            except RateLimitExceeded:
                await websocket.send_json({
                    "type": "error",
                    "message": "Daily API limit reached. Please try again tomorrow.",
                })
            except Exception as e:
                logger.error(f"Error processing WS command: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "message": f"Error: {str(e)}",
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/api/events")
async def get_events(user_id: str):
    """Get upcoming events for a user (used by frontend calendar widget)."""
    import asyncio

    session = dependencies.get_session(user_id)

    if not hasattr(session, "calendar_manager") or not session.calendar_manager:
        raise HTTPException(status_code=401, detail="Please sign in with Google first.")

    try:
        events_str = await asyncio.to_thread(session.calendar_manager.read_events, {})
        return {"events": events_str}
    except Exception as e:
        logger.error(f"Error reading events for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- OAuth Routes ---

# Server-side storage for PKCE code verifiers, keyed by OAuth state token.
# In production, use a short-TTL cache (Redis) instead of an in-memory dict.
_oauth_states: Dict[str, str] = {}


@router.get("/auth/login")
async def login():
    """Start Google OAuth flow."""
    if not dependencies.auth_manager:
        raise HTTPException(status_code=500, detail="Auth manager not initialized")

    state = secrets.token_urlsafe(32)
    url, code_verifier = dependencies.auth_manager.get_authorization_url(state)
    if code_verifier:
        _oauth_states[state] = code_verifier
    return RedirectResponse(url)


@router.get("/auth/callback")
async def auth_callback(code: str, state: str):
    """Handle Google OAuth callback."""
    if not dependencies.auth_manager:
        raise HTTPException(status_code=500, detail="Auth manager not initialized")

    try:
        code_verifier = _oauth_states.pop(state, None)
        creds = dependencies.auth_manager.exchange_code(code, code_verifier=code_verifier)

        user_info = dependencies.auth_manager.get_user_info(creds)
        user_id = user_info.get("id")

        if not user_id:
            logger.error("Could not get user ID from Google")
            return RedirectResponse("/?error=no_user_id")

        # Save credentials
        dependencies.auth_manager.token_store.save(user_id, creds_to_dict(creds))

        # Pre-warm session
        dependencies.get_session(user_id)

        logger.info(f"User {user_id} logged in successfully")

        name = user_info.get("name", "User")
        picture = user_info.get("picture", "")

        params = urlencode({
            "user_id": user_id,
            "name": name,
            "picture": picture,
        })

        return RedirectResponse(f"/?{params}")

    except Exception as e:
        logger.error(f"OAuth callback failed: {e}", exc_info=True)
        return RedirectResponse(f"/?error={str(e)}")


@router.get("/auth/logout")
async def logout(request: Request):
    """Log out user and revoke tokens."""
    return RedirectResponse("/")
