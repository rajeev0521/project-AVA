"""
AVA API Server — FastAPI entry point.

Initializes all shared resources in the lifespan context manager,
registers route modules, and serves the frontend.
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pathlib

from supabase import create_client

from ava.config import config
from ava.logger import get_logger
from ava.calendar.auth import AuthManager
from ava.api.token_store import SupabaseTokenStore, NullTokenStore
from ava.rate_limiter import RateLimiter
from ava.conversation.state_manager import SessionManager
from ava.brain.tool_router import ToolRouter
from ava.tools.time_tool import TimeTool
from ava.api import dependencies

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for global resources."""
    logger.info("Starting AVA API server...")

    # 1. Initialize Supabase
    supabase_url = config.supabase_url
    supabase_key = config.supabase_key
    if not supabase_url or not supabase_key:
        logger.warning("Supabase credentials missing. Features requiring persistence will fail.")
        dependencies.supabase = None
    else:
        dependencies.supabase = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized")

    # 2. Initialize Auth Manager
    if dependencies.supabase:
        token_store = SupabaseTokenStore(dependencies.supabase)
        dependencies.auth_manager = AuthManager(token_store=token_store)
    else:
        dependencies.auth_manager = AuthManager(token_store=NullTokenStore())

    # 3. Initialize Rate Limiter & Session Manager
    dependencies.rate_limiter = RateLimiter(max_rpm=15, max_rpd=1500)
    dependencies.session_manager = SessionManager(max_sessions=100, ttl_seconds=1800)

    from ava.tools.calendar_tool import (
        CreateCalendarEventTool, ReadCalendarEventsTool, UpdateCalendarEventTool, 
        DeleteCalendarEventTool, ResolveCalendarEventTool, FindCalendarEventTool
    )
    from ava.tools.memory_tool import (
        SaveUserPreferenceTool, ListUserPreferencesTool, DeleteUserPreferenceTool
    )
    from ava.tools.scheduler_tool import (
        CheckConflictsTool, FindFreeSlotsTool, SuggestAlternativesTool
    )
    tools = [
        TimeTool(),
        CreateCalendarEventTool(),
        ReadCalendarEventsTool(),
        UpdateCalendarEventTool(),
        DeleteCalendarEventTool(),
        ResolveCalendarEventTool(),
        FindCalendarEventTool(),
        SaveUserPreferenceTool(),
        ListUserPreferencesTool(),
        DeleteUserPreferenceTool(),
        CheckConflictsTool(),
        FindFreeSlotsTool(),
        SuggestAlternativesTool(),
    ]
    tool_router = ToolRouter(tools=tools)

    # 5. Initialize Command Service (lazy import to avoid circular deps)
    from ava.api.command_service import CommandService
    dependencies.command_service = CommandService(tool_router)

    logger.info("AVA API server successfully started")
    yield

    logger.info("Shutting down AVA API server...")


app = FastAPI(
    title="AVA Calendar Assistant API",
    description="Backend API for AVA voice-activated calendar assistant",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
CORS_ORIGINS = config.cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
from ava.api.routes import chat, calendar, memory  # noqa: E402

app.include_router(chat.router)
app.include_router(calendar.router)
app.include_router(memory.router)

# Mount Frontend (Static files)
_frontend_dir = pathlib.Path(__file__).parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
