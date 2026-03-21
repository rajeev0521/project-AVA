import speech_recognition as sr
import sounddevice as sd
import numpy as np
from scipy.io import wavfile
import tempfile
import os
import whisper
import pyaudio
from dotenv import load_dotenv
import Speech_manager
import openwakeword
from openwakeword.model import Model

class VoiceProcessor:
    def __init__(self):
        load_dotenv()
        self.recognizer = sr.Recognizer()
        
        # OpenWakeWord configuration
        openwakeword.utils.download_models() # download pre-trained if needed
        model_path = os.getenv("WAKE_WORD_MODEL", "hey_ava.onnx")
        self.threshold = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
        
        # Resolve absolute path for custom models vs built-in strings
        if model_path.endswith(".onnx") or model_path.endswith(".tflite"):
            # Check custom model path in current dir
            abs_model_path = os.path.join(os.path.dirname(__file__), model_path)
            if not os.path.exists(abs_model_path):
                 print(f"Warning: Wake word model not found at {abs_model_path}. Using fallback 'hey jarvis'. Please generate it using the instructions in how_to_train_hey_ava.md!")
                 model_path = "hey jarvis"
            else:
                 model_path = abs_model_path
        
        self.model = Model(wakeword_models=[model_path], inference_framework="onnx")
        self.chunk_size = 1280  # 1280 samples = 80ms audio chunk for openwakeword
        self.audio_stream = None
        
    def detect_wake_word(self):
        """Listen for wake words"""
        print(f"Listening for wake word (Threshold: {self.threshold})...")
        pa = pyaudio.PyAudio()
        self.audio_stream = pa.open(
            rate=16000,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.chunk_size
        )
        try:
            import time
            last_print = time.time()

            while True:
                pcm = self.audio_stream.read(self.chunk_size, exception_on_overflow=False)
                pcm_array = np.frombuffer(pcm, dtype=np.int16)
                
                # Get predictions for the frame
                prediction = self.model.predict(pcm_array)
                
                # Check if any model's score exceeds the threshold
                for mdl, score in prediction.items():
                    # Debug print every 1.5 seconds so we can verify the mic works
                    if time.time() - last_print > 1.5:
                        vol = np.max(np.abs(pcm_array))
                        print(f"[DEBUG] Mic Volume: {vol} | 'hey jarvis' Score: {score:.3f}")
                        last_print = time.time()

                    if score >= self.threshold:
                        print(f"Wake word detected! (Score: {score:.2f})\n")
                        return True
        except KeyboardInterrupt:
            print("Stopped listening for wake word.")
            raise
        except Exception as e:
            print(f"Error during wake word detection: {e}")
        finally:
            if self.audio_stream is not None:
                self.audio_stream.close()
        return False
    
    def listen_command(self):
        """Listen for a voice command after wake word detection"""
        print("Listening for command...")
        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source)
            audio = self.recognizer.listen(source, timeout=10)
            try:
                # Use whisper for local speech recognition
                text = self.recognizer.recognize_whisper(audio, model="base")
                return text
            except sr.UnknownValueError:
                print("Could not understand audio")
                return None
            except sr.RequestError as e:
                print(f"Could not request results from Whisper; {e}")
                return None
    
    def speak(self, text):
        """Convert text to speech using Speech_manager"""
        print(f"AVA: {text}")
        Speech_manager.speak(text) 