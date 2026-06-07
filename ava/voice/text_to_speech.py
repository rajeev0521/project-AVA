"""
Speech/TTS manager for AVA.
Provides text-to-speech using ElevenLabs with pyttsx3 fallback.
Supports interruption ("Stop").
"""

import os
import threading
import traceback
from .logger import get_logger

logger = get_logger(__name__)

# Global stop event for interrupting speech
_stop_event = threading.Event()
_is_speaking = False

# Pyttsx3 fallback engine
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
                logger.info("pyttsx3 TTS engine initialized")
    return _engine

def stop_speaking():
    """Interrupt the current speech."""
    global _is_speaking
    if _is_speaking:
        logger.info("Interrupting speech...")
        _stop_event.set()

def is_speaking() -> bool:
    return _is_speaking

def speak(text: str, blocking: bool = True):
    """
    Speak the given text aloud. Uses ElevenLabs if available, else pyttsx3.
    """
    if blocking:
        _speak_sync(text)
    else:
        thread = threading.Thread(target=_speak_sync, args=(text,), daemon=True)
        thread.start()

def _speak_sync(text: str):
    global _is_speaking
    _stop_event.clear()
    _is_speaking = True

    try:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if api_key and api_key.strip():
            success = _speak_elevenlabs(text, api_key)
            if not success:
                logger.warning("ElevenLabs failed, falling back to pyttsx3.")
                _speak_pyttsx3(text)
        else:
            _speak_pyttsx3(text)
    except Exception as e:
        logger.error(f"Error in TTS execution: {e}")
        logger.error(traceback.format_exc())
    finally:
        _is_speaking = False

def _speak_elevenlabs(text: str, api_key: str) -> bool:
    try:
        from elevenlabs.client import ElevenLabs
        import pyaudio

        client = ElevenLabs(api_key=api_key)
        
        # Generator yielding chunks
        audio_stream = client.text_to_speech.convert_as_stream(
            text=text,
            voice_id="JBFqnCBcs6BaNtIGlENa", # Default ID
            output_format="pcm_16000",
            model_id="eleven_turbo_v2_5"
        )
        
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=16000,
                        output=True)
        try:
            for chunk in audio_stream:
                if _stop_event.is_set():
                    logger.info("ElevenLabs TTS interrupted.")
                    break
                if chunk:
                    stream.write(chunk)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
        return True
    except ImportError:
        logger.warning("elevenlabs or pyaudio package not found.")
        return False
    except Exception as e:
        logger.error(f"ElevenLabs error: {e}")
        return False

def _speak_pyttsx3(text: str):
    try:
        engine = _get_engine()
        with _engine_lock:
            def onWord(name, location, length):
                if _stop_event.is_set():
                    engine.stop()

            # It's okay if this attaches multiple times, they just all check the same flag.
            engine.connect('started-word', onWord)
            
            engine.say(text)
            engine.runAndWait()
    except Exception as e:
        logger.error(f"pyttsx3 error: {e}")