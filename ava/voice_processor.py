import speech_recognition as sr
import sounddevice as sd
import numpy as np
from scipy.io import wavfile
import tempfile
import os
import whisper
import pvporcupine
import pyaudio
from dotenv import load_dotenv
from ava import Speech_manager

class VoiceProcessor:
    def __init__(self):
        load_dotenv()  # Add this line to load .env variables
        access_key = os.getenv("PORCUPINE_ACCESS_KEY")
        if not access_key:
            raise ValueError("PORCUPINE_ACCESS_KEY not found in environment variables")
        self.recognizer = sr.Recognizer()
        self.sample_rate = 16000
        self.porcupine_keyword_paths = [
            os.path.join(os.path.dirname(__file__), "hey-ava_en_windows_v3_0_0", "hey-ava_en_windows_v3_0_0.ppn")
        ]
        self.porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=self.porcupine_keyword_paths
        )
        self.audio_stream = None
        
    def detect_wake_word(self):
        """Listen for wake words"""
        print("Listening for wake word...")
        pa = pyaudio.PyAudio()
        self.audio_stream = pa.open(
            rate=self.porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self.porcupine.frame_length
        )
        try:
            while True:
                pcm = self.audio_stream.read(self.porcupine.frame_length, exception_on_overflow=False)
                pcm = np.frombuffer(pcm, dtype=np.int16)
                keyword_index = self.porcupine.process(pcm)
                if keyword_index >= 0:
                    print("Wake word detected!\n")
                    return True
        except KeyboardInterrupt:
            print("Stopped listening for wake word.")
        finally:
            if self.audio_stream is not None:
                self.audio_stream.close()
            pa.terminate()
        return False
    
    def listen_command(self):
        """Listen for a voice command after wake word detection"""
        print("Listening for command...")
        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source)
            audio = self.recognizer.listen(source, timeout=10)
            try:
                text = self.recognizer.recognize_google(audio)
                return text
            except sr.UnknownValueError:
                print("Could not understand audio")
                return None
            except sr.RequestError:
                print("Could not request results from speech recognition service")
                return None
    
    def speak(self, text):
        """Convert text to speech using Speech_manager"""
        print(f"AVA: {text}")
        Speech_manager.speak(text) 