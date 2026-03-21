import pyttsx3

# Initialize the TTS engine
engine = pyttsx3.init()

def speak(text: str):
    """
    Speak the given text aloud using the system's TTS engine.
    :param text: The text to be spoken.
    """
    engine.say(text)
    engine.runAndWait() 