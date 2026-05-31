"""
Speech/TTS manager for AVA.
Provides non-blocking text-to-speech using pyttsx3.
"""

import threading
from .logger import get_logger

logger = get_logger(__name__)

# Lazy-initialized TTS engine (avoids crash if no audio device at import time)
_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    """Lazy-initialize the TTS engine on first use."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                import pyttsx3
                _engine = pyttsx3.init()
                logger.info("TTS engine initialized")
    return _engine


def speak(text: str, blocking: bool = True):
    """
    Speak the given text aloud using the system's TTS engine.
    
    Args:
        text: The text to be spoken.
        blocking: If False, runs TTS in a background thread.
    """
    if blocking:
        _speak_sync(text)
    else:
        thread = threading.Thread(target=_speak_sync, args=(text,), daemon=True)
        thread.start()


def _speak_sync(text: str):
    """Synchronous TTS execution."""
    try:
        engine = _get_engine()
        with _engine_lock:
            engine.say(text)
            engine.runAndWait()
    except Exception as e:
        logger.error(f"TTS error: {e}")