"""
Voice Processor for AVA (Desktop mode).
Handles wake word detection, voice input via Whisper, and TTS output.
"""

import tempfile
import os
import time
from dotenv import load_dotenv

from . import speech_manager

try:
    import speech_recognition as sr
    import numpy as np
    import whisper
    import pyaudio
    import openwakeword
    from openwakeword.model import Model
    VOICE_DEPS_AVAILABLE = True
except ImportError:
    VOICE_DEPS_AVAILABLE = False


from .logger import get_logger

logger = get_logger(__name__)


class VoiceProcessor:
    def __init__(self):
        if not VOICE_DEPS_AVAILABLE:
            raise RuntimeError("Desktop voice dependencies are not installed. Please install with `pip install .[desktop]`")
        load_dotenv()
        self.recognizer = sr.Recognizer()
        
        # OpenWakeWord configuration
        openwakeword.utils.download_models()  # download pre-trained if needed
        model_path = os.getenv("WAKE_WORD_MODEL", "hey_ava.onnx")
        self.threshold = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
        
        # Resolve absolute path for custom models vs built-in strings
        if model_path.endswith(".onnx") or model_path.endswith(".tflite"):
            # Check custom model path in current dir
            abs_model_path = os.path.join(os.path.dirname(__file__), model_path)
            if not os.path.exists(abs_model_path):
                logger.warning(
                    f"Wake word model not found at {abs_model_path}. "
                    "Using fallback 'hey jarvis'. "
                    "Please generate it using the instructions in how_to_train_hey_ava.md!"
                )
                model_path = "hey jarvis"
            else:
                model_path = abs_model_path
        
        self.model = Model(wakeword_models=[model_path], inference_framework="onnx")
        self.chunk_size = 1280  # 1280 samples = 80ms audio chunk for openwakeword
        self.audio_stream = None
        
        # Load Whisper model ONCE at init time (not per transcription)
        whisper_model_name = os.getenv("WHISPER_MODEL", "tiny")
        logger.info(f"Loading Whisper '{whisper_model_name}' model (one-time)...")
        self.whisper_model = whisper.load_model(whisper_model_name)
        logger.info(f"Whisper model loaded successfully")
        
        # One-time ambient noise calibration
        self._noise_calibrated = False
        self._calibrate_noise()
        
    def _calibrate_noise(self):
        """One-time ambient noise calibration at startup."""
        if self._noise_calibrated:
            return
        try:
            logger.info("Calibrating ambient noise (one-time)...")
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
            self._noise_calibrated = True
            logger.info("Noise calibration complete")
        except Exception as e:
            logger.warning(f"Noise calibration failed (will retry): {e}")
        
    def detect_wake_word(self):
        """Listen for wake words"""
        logger.info(f"Listening for wake word (Threshold: {self.threshold})...")
        pa = pyaudio.PyAudio()
        self.audio_stream = pa.open(
            rate=16000,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.chunk_size
        )
        try:
            last_print = time.time()

            while True:
                pcm = self.audio_stream.read(self.chunk_size, exception_on_overflow=False)
                pcm_array = np.frombuffer(pcm, dtype=np.int16)
                
                # Get predictions for the frame
                prediction = self.model.predict(pcm_array)
                
                # Check if any model's score exceeds the threshold
                for mdl, score in prediction.items():
                    # Debug print every 5 seconds (reduced frequency)
                    if time.time() - last_print > 5.0:
                        vol = np.max(np.abs(pcm_array))
                        logger.debug(f"Mic Volume: {vol} | Wake word score: {score:.3f}")
                        last_print = time.time()

                    if score >= self.threshold:
                        logger.info(f"Wake word detected! (Score: {score:.2f})")
                        return True
        except KeyboardInterrupt:
            logger.info("Stopped listening for wake word.")
            raise
        except Exception as e:
            logger.error(f"Error during wake word detection: {e}")
        finally:
            if self.audio_stream is not None:
                self.audio_stream.close()
        return False
    
    def listen_command(self):
        """Listen for a voice command after wake word detection"""
        logger.info("Listening for command...")
        
        # Ensure noise is calibrated
        if not self._noise_calibrated:
            self._calibrate_noise()
        
        with sr.Microphone() as source:
            audio = self.recognizer.listen(source, timeout=10)
            try:
                # Save audio to temp file for Whisper
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(audio.get_wav_data())
                    tmp_path = tmp.name
                
                # Use the pre-loaded Whisper model (no reload!)
                result = self.whisper_model.transcribe(tmp_path, fp16=False)
                text = result["text"].strip()
                
                # Cleanup temp file
                os.unlink(tmp_path)
                
                logger.info(f"Transcribed: {text}")
                return text
            except sr.UnknownValueError:
                logger.warning("Could not understand audio")
                return None
            except Exception as e:
                logger.error(f"Transcription error: {e}")
                return None
    
    def speak(self, text, blocking=True):
        """Convert text to speech using speech_manager"""
        logger.info(f"AVA: {text}")
        speech_manager.speak(text, blocking=blocking)