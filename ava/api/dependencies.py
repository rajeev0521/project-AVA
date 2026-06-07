"""
Shared dependencies for AVA API endpoints.

All globals are initialized during the server lifespan (see server.py).
Route handlers access these via `from ava.api import dependencies`.
"""

# Global state initialized in server lifecycle
supabase = None
auth_manager = None
rate_limiter = None
session_manager = None
command_service = None


def get_session(user_id: str):
    """
    Retrieve existing session or create a new one.

    Attaches per-user CalendarManager and LongTermMemory lazily
    on first access (avoids importing heavy modules at startup).
    """
    session = session_manager.get_session(user_id)

    if not session:
        session = session_manager.create_session(user_id)

    # Lazily attach per-user managers if not already present
    if not hasattr(session, "calendar_manager"):
        from ava.calendar.calendar_service import CalendarManager

        session.calendar_manager = CalendarManager(auth_manager, user_id) if auth_manager else None

    if not hasattr(session, "memory_manager"):
        try:
            from ava.memory.long_term_memory import LongTermMemory

            session.memory_manager = LongTermMemory()
        except Exception:
            session.memory_manager = None

    return session
