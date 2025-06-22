import os
import time
from dotenv import load_dotenv
from ava.voice_processor import VoiceProcessor
from ava.calendar_manager import CalendarManager
from ava.nlp_processor import NLPProcessor
from ava.auth_manager import AuthManager
import speech_recognition as sr

class AVASession:
    def __init__(self):
        self.awaiting_confirmation = False
        self.pending_action = None
        self.pending_data = None
        self.last_intent = None
        self.last_entities = None

class AVA:
    def __init__(self):
        load_dotenv()
        self.auth_manager = AuthManager()
        self.voice_processor = VoiceProcessor()
        self.calendar_manager = CalendarManager(self.auth_manager)
        self.nlp_processor = NLPProcessor()
        self.session = AVASession()
        
    def start(self):
        print("I'm listening...")
        while True:
            try:
                # If awaiting confirmation, listen for confirmation directly (no wake word)
                if self.session.awaiting_confirmation:
                    command = self.voice_processor.listen_command()
                    if command:
                        if command.strip().lower() in ["yes", "confirm", "delete all", "proceed"]:
                            if self.session.pending_action == "delete_events":
                                result = self.calendar_manager.confirm_delete_events(self.session.pending_data)
                                self.session.awaiting_confirmation = False
                                self.session.pending_action = None
                                self.session.pending_data = None
                                self.voice_processor.speak(result)
                                continue
                        elif command.strip().lower() in ["no", "cancel", "abort"]:
                            self.voice_processor.speak("Okay, no events were deleted.")
                            self.session.awaiting_confirmation = False
                            self.session.pending_action = None
                            self.session.pending_data = None
                            continue
                        else:
                            # Not a confirmation, treat as a new command
                            self.session.awaiting_confirmation = False
                            self.session.pending_action = None
                            self.session.pending_data = None
                            # Process as new command below
                    else:
                        continue  # If no command, keep waiting for confirmation
                # Normal flow: wait for wake word
                if self.voice_processor.detect_wake_word():
                    print("Wake word detected! How can I help you?")
                    command = self.voice_processor.listen_command()
                    if command:
                        print(command)
                        # Process command using NLP
                        intent, entities = self.nlp_processor.process_command(command)
                        self.session.last_intent = intent
                        self.session.last_entities = entities
                        if intent:
                            # Execute calendar operation
                            action_result = self.calendar_manager.execute_command(intent, entities)
                            # Check for bulk delete confirmation
                            if (
                                intent == "delete_event" and
                                "Please confirm if you want to delete all these events." in action_result
                            ):
                                event_ids = self.calendar_manager.get_pending_delete_event_ids(entities)
                                self.session.awaiting_confirmation = True
                                self.session.pending_action = "delete_events"
                                self.session.pending_data = event_ids
                                self.voice_processor.speak(action_result)
                                continue
                            # Generate natural language response
                            response = self.nlp_processor.generate_response(action_result, intent, entities)
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