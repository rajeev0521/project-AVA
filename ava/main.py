import os
import time
from dotenv import load_dotenv
from voice_processor import VoiceProcessor
from calendar_manager import CalendarManager
from nlp_processor import NLPProcessor
from auth_manager import AuthManager
import speech_recognition as sr

class AVA:
    def __init__(self):
        load_dotenv()
        self.auth_manager = AuthManager()
        self.voice_processor = VoiceProcessor()
        self.calendar_manager = CalendarManager(self.auth_manager)
        self.nlp_processor = NLPProcessor()
        
    def start(self):
        print("I'm listening...")
        while True:
            try:
                # Listen for wake word
                if self.voice_processor.detect_wake_word():
                    print("Wake word detected! How can I help you?")
                    
                    # Get voice command
                    command = self.voice_processor.listen_command()
                    if command:
                        print(command)
                        
                        # Process command using NLP
                        intent, entities = self.nlp_processor.process_command(command)
                        
                        if intent:
                            # Execute calendar operation
                            action_result = self.calendar_manager.execute_command(intent, entities)
                            
                            # Generate natural language response
                            response = self.nlp_processor.generate_response(action_result)
                        else:
                            response = "I'm sorry, I couldn't understand what you want me to do with your calendar."
                        
                        # Speak response
                        self.voice_processor.speak(response)
                        
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"An error occurred: {str(e)}")
                time.sleep(1)

if __name__ == "__main__":
    ava = AVA()
    ava.start()

    # List available microphones
    mic_list = sr.Microphone.list_microphone_names()
    print(mic_list) 